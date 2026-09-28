"""Gemini web-research adapter implementing the ResearchProvider contract.

Research/enrichment ONLY — grounded web lookup for metadata the structured
providers cannot supply (sector/industry classification for dynamic equities,
peer candidates, business context, news digests). NEVER queried for market
data (prices/OHLCV/volume/timestamps/ratios) and NEVER a replacement for the
deterministic financial engine. No website scraping: all web evidence comes
from Gemini's official Google Search grounding.

Uses the official Google GenAI SDK (``google-genai``)::

    from google import genai
    from google.genai import types
    client = genai.Client(api_key=GEMINI_API_KEY)

Secret handling (mirrors the Upstox/NewsAPI adapters):
- Key comes exclusively from configuration (GEMINI_API_KEY env var) and is
  passed ONLY to ``genai.Client(api_key=...)`` — never in URLs, never in
  logs, never in errors, never in responses. The SDK itself sends it as a
  header; FinCortext never formats it into any string.
- Missing key -> ProviderUnavailableError; auth failures -> same with a
  distinct diagnostic; model-not-found -> distinct diagnostic naming the
  model; rate limits / timeouts / grounding problems each get their own
  sanitized message. Nothing is fabricated on failure.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from google import genai
from google.genai import types
from google.genai.errors import APIError

from app.core.exceptions import ProviderError, ProviderUnavailableError
from app.core.logging import get_logger
from app.domain.contracts.providers import ResearchProvider

logger = get_logger("providers.gemini_research")


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _domain_of(url: str) -> str | None:
    try:
        from urllib.parse import urlparse

        host = urlparse(url).netloc.lower()
        return host.removeprefix("www.") or None
    except Exception:
        return None


_COMPANY_SCHEMA: dict = {
    "type": "OBJECT",
    "properties": {
        "company_name": {"type": "STRING"},
        "sector": {"type": "STRING"},
        "industry": {"type": "STRING"},
        "business_description": {"type": "STRING"},
        "confidence": {"type": "NUMBER"},
        "peers": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "symbol": {"type": "STRING"},
                    "name": {"type": "STRING"},
                    "reason": {"type": "STRING"},
                },
            },
        },
    },
    "required": ["company_name", "sector", "industry"],
}

_PEERS_SCHEMA: dict = {
    "type": "OBJECT",
    "properties": {
        "peers": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "symbol": {"type": "STRING"},
                    "name": {"type": "STRING"},
                    "reason": {"type": "STRING"},
                },
                "required": ["symbol"],
            },
        },
    },
    "required": ["peers"],
}

_NEWS_SCHEMA: dict = {
    "type": "OBJECT",
    "properties": {
        "items": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "title": {"type": "STRING"},
                    "summary": {"type": "STRING"},
                    "url": {"type": "STRING"},
                    "source": {"type": "STRING"},
                    "published_at": {"type": "STRING"},
                },
                "required": ["title"],
            },
        },
    },
    "required": ["items"],
}


class GeminiResearchProvider(ResearchProvider):
    """Grounded Gemini research via the official GenAI SDK. Replaceable."""

    name = "gemini_research"

    def __init__(
        self,
        api_key: str | None,
        *,
        model: str = "gemini-2.5-flash",
        timeout_seconds: int = 30,
        web_search_enabled: bool = True,
    ):
        # Key comes exclusively from configuration (GEMINI_API_KEY env var).
        self._api_key = (api_key or "").strip()
        self._model = (model or "gemini-2.5-flash").strip() or "gemini-2.5-flash"
        self._timeout = max(5, int(timeout_seconds or 30))
        self._web_search = bool(web_search_enabled)
        self._client: Any = None
        self._last_sources: list[dict] = []
        self._last_grounded: bool = False

    @property
    def is_configured(self) -> bool:
        return bool(self._api_key)

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def grounding_enabled(self) -> bool:
        """Whether Search grounding is configured (independent of results)."""
        return self._web_search

    # -- ResearchProvider contract --------------------------------------------

    def verify_model(self) -> dict:
        """Check the configured model can actually GENERATE with the key.

        A metadata lookup alone is insufficient (a model can be listed yet
        refuse generation). Sends one minimal prompt; returns {"ok", "model",
        "error"|None} with sanitized diagnostics — never raises, never leaks
        the key. Use before company research when the model is in doubt.
        """
        if not self.is_configured:
            return {
                "ok": False,
                "model": self._model,
                "error": "GEMINI_API_KEY is not configured.",
            }
        try:
            client = self._client_or_raise()
            try:
                resp = client.models.generate_content(
                    model=self._model,
                    contents="Reply with the single word: ok",
                    config=types.GenerateContentConfig(temperature=0),
                )
            except APIError as exc:
                mapped = self._map_api_error(exc)
                return {"ok": False, "model": self._model, "error": mapped.message}
            text = (getattr(resp, "text", None) or "").strip()
            if not text:
                return {
                    "ok": False,
                    "model": self._model,
                    "error": "Model reachable but returned an empty response.",
                }
            return {"ok": True, "model": self._model, "error": None}
        except ProviderUnavailableError as exc:
            return {"ok": False, "model": self._model, "error": exc.message}
        except ProviderError as exc:
            return {"ok": False, "model": self._model, "error": exc.message}
        except Exception:
            logger.exception("Gemini model verification failed")
            return {"ok": False, "model": self._model, "error": "verification failed"}

    def research_company(self, symbol: str, company_name: str) -> dict:
        """Classify a company's sector/industry via grounded web search."""
        self._require_configured()
        prompt = (
            "You are a financial-research assistant for Indian equities. "
            f"Research the CURRENT business and industry classification of the NSE-listed company "
            f"'{company_name}' (trading symbol {symbol}).\n"
            "Use web search and ground every claim in current sources. "
            "Return ONLY the requested JSON: company_name (official name), sector "
            "(broad sector, e.g. Utilities, Energy, Financial Services), industry "
            "(narrow industry, e.g. Power Generation, Private Sector Bank), "
            "business_description (2-3 sentences on what the company does), "
            "confidence (0-1 for the classification), and up to 6 peers "
            "(NSE trading symbols of listed Indian competitors with one-line reasons)."
        )
        payload = self._generate(prompt, _COMPANY_SCHEMA)
        company = (payload.get("company_name") or company_name or "").strip()
        sector = (payload.get("sector") or "").strip()
        industry = (payload.get("industry") or "").strip()
        if not sector or not industry:
            raise ProviderError(
                "Gemini returned a company classification without sector/industry.",
                details={"provider": self.name},
            )
        try:
            confidence = float(payload.get("confidence", 0.5))
        except (TypeError, ValueError):
            confidence = 0.5
        confidence = max(0.0, min(1.0, confidence))
        return {
            "company_name": company,
            "sector": sector,
            "industry": industry,
            "business_description": (payload.get("business_description") or "").strip() or None,
            "confidence": confidence,
            "peers": self._clean_peers(payload.get("peers"), symbol),
            "sources": self._last_sources,
            "grounded": self._last_grounded,
            "model": self._model,
            "retrieved_at": _utcnow_iso(),
        }

    def suggest_peers(
        self,
        symbol: str,
        company_name: str,
        sector: str,
        industry: str,
        *,
        max_peers: int = 8,
    ) -> dict:
        """Suggest listed peer candidates (validated downstream via Upstox)."""
        self._require_configured()
        prompt = (
            "You are a financial-research assistant for Indian equities. "
            f"List NSE-listed competitor companies most relevant to '{company_name}' "
            f"(trading symbol {symbol}), sector '{sector}', industry '{industry}'. "
            "Prefer the same industry, then the same sector, then closely related "
            "sectors. Use web search. Return ONLY the requested JSON: peers as NSE "
            "trading symbols (e.g. RELIANCE, TCS — the exact symbols used on the "
            "National Stock Exchange of India) with official company names and a "
            "one-line relevance reason each. Only real listed companies — never "
            "invent symbols."
        )
        payload = self._generate(prompt, _PEERS_SCHEMA)
        return {
            "peers": self._clean_peers(payload.get("peers"), symbol)[: max(1, int(max_peers or 8))],
            "sources": self._last_sources,
            "grounded": self._last_grounded,
            "model": self._model,
            "retrieved_at": _utcnow_iso(),
        }

    def research_news(self, symbol: str, company_name: str) -> dict:
        """Web-research digest of recent company developments (labeled research)."""
        self._require_configured()
        prompt = (
            "You are a financial-research assistant for Indian equities. "
            f"Using web search, find the most recent (last 30 days if possible) "
            f"business/financial developments for NSE-listed '{company_name}' "
            f"(trading symbol {symbol}): earnings, orders, projects, regulatory "
            "actions, leadership, or market-moving events. Return ONLY the "
            "requested JSON: items with title, 1-2 sentence summary, source URL, "
            "publication name, and publication date (ISO) when known. Only real "
            "findings with URLs — never invent stories."
        )
        payload = self._generate(prompt, _NEWS_SCHEMA)
        items = []
        for raw in payload.get("items") or []:
            if not isinstance(raw, dict):
                continue
            title = str(raw.get("title") or "").strip()
            if not title:
                continue
            url = str(raw.get("url") or "").strip() or None
            items.append(
                {
                    "title": title,
                    "summary": str(raw.get("summary") or "").strip() or None,
                    "url": url,
                    "source": str(raw.get("source") or "").strip() or (_domain_of(url) if url else None),
                    "published_at": str(raw.get("published_at") or "").strip() or None,
                }
            )
        return {
            "items": items,
            "sources": self._last_sources,
            "grounded": self._last_grounded,
            "model": self._model,
            "retrieved_at": _utcnow_iso(),
        }

    # -- internals ---------------------------------------------------------------

    def _require_configured(self) -> None:
        if not self.is_configured:
            raise ProviderUnavailableError(
                "GEMINI_API_KEY is not configured — web research is "
                "unavailable. Set GEMINI_API_KEY in the environment/.env to "
                "enable it.",
                details={"provider": self.name},
            )

    def _client_or_raise(self):
        """Build the SDK client (key passed as a constructor arg only)."""
        self._require_configured()
        if self._client is None:
            try:
                # Timeout is milliseconds per HttpOptions. The key travels
                # only inside the SDK client — never in URLs or log strings.
                self._client = genai.Client(
                    api_key=self._api_key,
                    http_options={"timeout": self._timeout * 1000},
                )
            except Exception as exc:
                raise ProviderError(
                    f"Gemini client setup failed: {type(exc).__name__}",
                    details={"provider": self.name},
                ) from exc
        return self._client

    def _generate(self, prompt: str, schema: dict) -> dict:
        """Generate grounded JSON via the SDK; return the parsed object."""
        client = self._client_or_raise()
        tools = None
        if self._web_search:
            # Official Google Search grounding — no website scraping.
            tools = [types.Tool(google_search=types.GoogleSearch())]
        try:
            resp = client.models.generate_content(
                model=self._model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=schema,
                    tools=tools,
                    temperature=0.2,
                ),
            )
        except APIError as exc:
            raise self._map_api_error(exc) from exc
        except Exception as exc:
            if "timeout" in type(exc).__name__.lower() or isinstance(exc, TimeoutError):
                raise ProviderError(
                    f"Gemini research request timed out after {self._timeout}s.",
                    details={"provider": self.name},
                ) from exc
            raise ProviderError(
                f"Gemini research request failed: {type(exc).__name__}",
                details={"provider": self.name},
            ) from exc
        return self._parse_response(resp)

    def _map_api_error(self, exc: APIError):
        """Sanitized diagnostics per failure class — credentials never included."""
        code = getattr(exc, "code", None)
        if code in (401, 403) or (code == 400 and self._looks_like_key_error(exc)):
            logger.warning("Gemini authentication failed (HTTP %s)", code)
            return ProviderUnavailableError(
                "Gemini API key is invalid or lacks access — check GEMINI_API_KEY.",
                details={"provider": self.name, "http_status": code},
            )
        if code == 404:
            logger.warning("Gemini model unavailable (HTTP 404): %s", self._model)
            return ProviderUnavailableError(
                f"Gemini model {self._model} is not available for this API "
                "key/project. Set GEMINI_MODEL to a supported model id.",
                details={"provider": self.name, "http_status": code, "model": self._model},
            )
        if code == 429:
            return ProviderError(
                "Gemini rate limit reached (HTTP 429). Retry later.",
                details={"provider": self.name},
            )
        if code in (500, 502, 503):
            return ProviderError(
                f"Gemini endpoint error (HTTP {code}). Retry later.",
                details={"provider": self.name, "http_status": code},
            )
        return ProviderError(
            f"Gemini request failed (HTTP {code}).",
            details={"provider": self.name, "http_status": code},
        )

    @staticmethod
    def _looks_like_key_error(exc: APIError) -> bool:
        text = f"{getattr(exc, 'message', '')}".lower()
        return any(
            token in text
            for token in ("api key", "apikey", "key not valid", "permission denied", "unauthorized")
        )

    def _parse_response(self, resp: Any) -> dict:
        """Extract the JSON object + grounding sources from an SDK response."""
        # Safety blocks surface here, not as exceptions.
        try:
            feedback = getattr(resp, "prompt_feedback", None)
            block_reason = getattr(feedback, "block_reason", None)
        except Exception:
            block_reason = None
        if block_reason:
            raise ProviderError(
                "Gemini declined the research request (content safety filter).",
                details={"provider": self.name},
            )
        text = (getattr(resp, "text", None) or "").strip()
        if not text:
            raise ProviderError(
                "Gemini returned an empty response.",
                details={"provider": self.name},
            )
        import json as _json

        try:
            data = _json.loads(text)
        except (ValueError, TypeError) as exc:
            raise ProviderError(
                "Gemini returned malformed JSON.",
                details={"provider": self.name},
            ) from exc
        if not isinstance(data, dict):
            raise ProviderError(
                "Gemini returned a non-object payload.",
                details={"provider": self.name},
            )
        # Grounding evidence: title/URL/domain per chunk + retrieval time.
        sources: list[dict] = []
        grounded = False
        try:
            candidates = getattr(resp, "candidates", None) or []
            meta = getattr(candidates[0], "grounding_metadata", None) if candidates else None
            chunks = getattr(meta, "grounding_chunks", None) or []
            for chunk in chunks:
                web = getattr(chunk, "web", None)
                uri = str(getattr(web, "uri", None) or "").strip()
                if not uri:
                    continue
                grounded = True
                sources.append(
                    {
                        "title": str(getattr(web, "title", None) or "").strip() or None,
                        "url": uri,
                        "domain": _domain_of(uri),
                        "retrieved_at": _utcnow_iso(),
                    }
                )
        except (IndexError, AttributeError, TypeError):
            pass
        if self._web_search and not grounded:
            logger.info("Gemini response carried no search-grounding citations")
        self._last_sources = sources
        self._last_grounded = grounded
        return data

    @staticmethod
    def _clean_peers(raw: Any, own_symbol: str) -> list[dict]:
        """Normalize peer rows; drop empties and the company itself."""
        out: list[dict] = []
        own = (own_symbol or "").strip().upper()
        for item in raw or []:
            if not isinstance(item, dict):
                continue
            sym = str(item.get("symbol") or "").strip().upper()
            if not sym or sym == own:
                continue
            out.append(
                {
                    "symbol": sym,
                    "name": str(item.get("name") or sym).strip(),
                    "reason": str(item.get("reason") or "").strip() or None,
                }
            )
        return out
