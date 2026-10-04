"""Central Stock Context: one reusable assembly per selected symbol.

Given any valid NSE symbol (curated universe or dynamically searched), this
service produces a complete, cached context object assembled from fields that
genuinely exist in Upstox responses (verified live) plus existing provider
data where Upstox does not cover a need:

- identity: resolved instrument (symbol, trading symbol, instrument_key,
  exchange, isin, exchange_token, instrument_type, tick/lot size) +
  sector/industry (universe config → official NSE Nifty 500 CSV → labeled
  Gemini research when needed);
- quote: live Upstox full quote (V3) with 5-level market depth, circuit
  limits and total buy/sell quantities; on failure the last stored snapshot
  is served (CACHED) — never fabricated;
- fifty_two_week: Upstox year_high/year_low (verified live fields);
- history: stored daily OHLCV series (Upstox candles through the normal
  validation/storage pipeline);
- profile: company/sector/industry + business description (labeled research
  when structured sources cannot classify);
- fundamentals: stored observations with per-metric source labels (ingested
  filings = primary; pre-consolidation imports = legacy_import; web-research
  enrichment = web_research) — provider-fundamentals refreshes are explicit;
- news: stored articles with explicit status (refresh is an explicit action).

Per-data-type TTLs (documented; quotes refresh often, profile rarely) keep a
session from re-fetching the same symbol redundantly across pages. Every
section carries an explicit status; genuinely unavailable fields are marked
unavailable — never fabricated.

Fields NOT available from Upstox for NSE equities (documented in
`UNAVAILABLE_FROM_UPSTOX`): market capitalization and shares outstanding
(no Upstox field), fundamental statements (no Upstox fundamentals API),
dividend history, analyst coverage.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from app.core.exceptions import NotFoundError
from app.core.logging import get_logger
from app.domain.models.base import DataStatus

logger = get_logger("services.stock_context")

# Per-data-type TTLs. Quotes refresh often; company profile rarely.
TTL_QUOTE_SECONDS = 60          # live quote: 1 minute
TTL_HISTORY_SECONDS = 3600      # stored daily OHLCV: 1 hour
TTL_PROFILE_SECONDS = 86400     # identity/sector/industry: 24 hours
TTL_FUNDAMENTALS_SECONDS = 21600  # fundamentals coverage: 6 hours
TTL_NEWS_SECONDS = 900          # stored news read: 15 minutes

# Fields users of a full investment platform expect that Upstox does NOT
# provide for NSE equities (verified against the live V3 full-quote payload).
# The context marks these explicitly — it never fabricates them.
UNAVAILABLE_FROM_UPSTOX = [
    "market_cap",
    "shares_outstanding",
    "fundamental_statements",
    "dividend_history",
    "analyst_coverage",
]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _fresh(stamp: datetime | None, ttl_seconds: int) -> bool:
    return stamp is not None and (_now() - stamp).total_seconds() < ttl_seconds


class StockContextService:
    """Assembles and caches the central Stock Context for one symbol."""

    def __init__(
        self,
        *,
        market_service,
        fundamentals_service,
        news_service,
        market_repo,
        financial_repo,
        news_repo,
        research_service=None,
    ):
        self.market_service = market_service
        self.fundamentals_service = fundamentals_service
        self.news_service = news_service
        self.market_repo = market_repo
        self.financial_repo = financial_repo
        self.news_repo = news_repo
        self.research_service = research_service
        # symbol (upper) -> per-section cache:
        # {"identity": (stamp, payload), "quote": ..., "history": ...,
        #  "profile": ..., "fundamentals": ..., "news": ...}
        self._cache: dict[str, dict] = {}

    # -- cache helpers ---------------------------------------------------------

    def _cached(self, symbol: str, section: str, ttl: int):
        sections = self._cache.get(symbol) or {}
        entry = sections.get(section)
        if not entry:
            return None
        stamp, payload = entry
        if not _fresh(stamp, ttl):
            return None
        return payload

    def _store(self, symbol: str, section: str, payload) -> None:
        self._cache.setdefault(symbol, {})[section] = (_now(), payload)

    def invalidate(self, symbol: str) -> None:
        """Drop all cached sections for one symbol (explicit refreshes)."""
        self._cache.pop((symbol or "").strip().upper(), None)

    # -- public assembly --------------------------------------------------------

    def get_stock_context(self, symbol: str, instrument_key: str | None = None) -> dict:
        """One service call: complete, cached Stock Context for one symbol.

        Never raises for provider problems — sections degrade honestly.
        Unknown symbols raise NotFoundError (honest 404 at the route).
        """
        raw = (symbol or "").strip()
        if not raw:
            raise NotFoundError("Empty symbol")
        canonical = raw.upper().replace(".NS", "") if raw.upper().endswith(".NS") else raw.upper()

        identity = self._identity(canonical, instrument_key)
        canonical = identity["symbol"]
        quote = self._quote(canonical, identity)
        fifty_two_week = self._fifty_two_week(quote)
        history = self._history(canonical)
        profile = self._profile(canonical, identity)
        fundamentals = self._fundamentals(canonical)
        news = self._news(canonical)

        return {
            "symbol": canonical,
            "name": profile.get("name") or identity.get("name") or canonical,
            "generated_at": _now().isoformat(),
            "identity": identity,
            "quote": quote,
            "fifty_two_week": fifty_two_week,
            "history": history,
            "profile": profile,
            "fundamentals": fundamentals,
            "news": news,
            "unavailable_from_upstox": list(UNAVAILABLE_FROM_UPSTOX),
        }

    # -- sections -----------------------------------------------------------------

    def _identity(self, symbol: str, instrument_key: str | None) -> dict:
        cached = self._cached(symbol, "identity", TTL_PROFILE_SECONDS)
        if cached and not instrument_key:
            return cached
        try:
            resolved = self.market_service.resolve_symbol(symbol, instrument_key)
        except NotFoundError as exc:
            payload = {
                "symbol": symbol,
                "name": None,
                "instrument_key": instrument_key,
                "exchange": "NSE",
                "segment": "EQ",
                "sector": None,
                "industry": None,
                "status": DataStatus.UNAVAILABLE.value,
                "error": exc.message,
            }
            return payload
        meta = self._instrument_meta(resolved)
        payload = {
            "symbol": resolved["symbol"],
            "name": resolved.get("name"),
            "trading_symbol": meta.get("trading_symbol") or resolved["symbol"],
            "instrument_key": resolved.get("instrument_key"),
            "exchange": resolved.get("exchange") or "NSE",
            "segment": "EQ",
            "isin": meta.get("isin"),
            "exchange_token": meta.get("exchange_token"),
            "instrument_type": meta.get("instrument_type"),
            "tick_size": meta.get("tick_size"),
            "lot_size": meta.get("lot_size"),
            "sector": resolved.get("sector"),
            "industry": resolved.get("industry"),
            "dynamic": resolved.get("dynamic", False),
            "status": DataStatus.LIVE.value if resolved.get("instrument_key") else DataStatus.UNAVAILABLE.value,
        }
        self._store(symbol, "identity", payload)
        return payload

    def _instrument_meta(self, resolved: dict) -> dict:
        """Best-effort instrument metadata (isin/tick/lot) from the registry."""
        key = resolved.get("instrument_key")
        if not key or self.market_service is None:
            return {}
        repo = getattr(self.market_service, "instrument_repo", None)
        if repo is None:
            return {}
        try:
            cached = repo.get_by_key(key)
            return dict(cached) if cached else {}
        except Exception:
            return {}

    def _quote(self, canonical: str, identity: dict) -> dict:
        cached = self._cached(canonical, "quote", TTL_QUOTE_SECONDS)
        if cached is not None:
            return cached
        try:
            quote = self.market_service.get_quote(canonical, identity.get("instrument_key"))
        except NotFoundError as exc:
            payload = {
                "symbol": canonical,
                "status": DataStatus.UNAVAILABLE.value,
                "live": False,
                "source": None,
                "available": False,
                "error": exc.message,
            }
            self._store(canonical, "quote", payload)
            return payload
        except Exception as exc:
            logger.warning("Quote fetch failed for %s: %s", canonical, type(exc).__name__)
            payload = {
                "symbol": canonical,
                "status": DataStatus.ERROR.value,
                "live": False,
                "source": None,
                "available": False,
                "error": f"{type(exc).__name__}",
            }
            self._store(canonical, "quote", payload)
            return payload
        quote["available"] = quote.get("last_price") is not None
        # Depth is ephemeral: a stored (CACHED) snapshot must never present
        # stale depth as current — only live Upstox quotes carry it.
        if not quote.get("live"):
            quote["depth_buy"] = None
            quote["depth_sell"] = None
            quote["total_buy_quantity"] = None
            quote["total_sell_quantity"] = None
        self._store(canonical, "quote", quote)
        return quote

    def _fifty_two_week(self, quote: dict) -> dict:
        high = quote.get("year_high")
        low = quote.get("year_low")
        return {
            "high": high,
            "low": low,
            "available": high is not None or low is not None,
            "source": quote.get("source") if (high is not None or low is not None) else None,
        }

    def _history(self, canonical: str) -> dict:
        cached = self._cached(canonical, "history", TTL_HISTORY_SECONDS)
        if cached is not None:
            return cached
        try:
            # Ensure cached OHLCV coverage first (Upstox when missing/stale),
            # then read the stored series from DuckDB.
            prepared = self.market_service.ensure_history([canonical], min_bars=5)
            series = self.market_service.get_price_series(canonical)
        except Exception as exc:
            logger.warning("History read failed for %s: %s", canonical, type(exc).__name__)
            payload = {
                "status": DataStatus.ERROR.value,
                "count": 0,
                "prices": [],
                "available": False,
                "error": f"{type(exc).__name__}",
            }
            self._store(canonical, "history", payload)
            return payload
        series["available"] = series["count"] > 0
        series["preparation"] = prepared
        self._store(canonical, "history", series)
        return series

    def _profile(self, canonical: str, identity: dict) -> dict:
        cached = self._cached(canonical, "profile", TTL_PROFILE_SECONDS)
        if cached is not None:
            return cached
        payload = {
            "name": identity.get("name") or canonical,
            "sector": identity.get("sector"),
            "industry": identity.get("industry"),
            "business_description": None,
            "source": "universe_config" if identity.get("sector") else None,
            "confidence": None,
            "sources": [],
            "status": DataStatus.LIVE.value if identity.get("sector") else DataStatus.UNAVAILABLE.value,
        }
        # Labeled research enrichment when structured sources cannot classify.
        if payload["status"] == DataStatus.UNAVAILABLE.value and self.research_service is not None:
            try:
                outcome = self.research_service.enrich_company(canonical, payload["name"])
            except Exception as exc:
                logger.warning(
                    "Profile research failed for %s: %s", canonical, type(exc).__name__
                )
                outcome = None
            if outcome and outcome.get("usable"):
                payload.update(
                    {
                        "sector": outcome.get("sector"),
                        "industry": outcome.get("industry"),
                        "business_description": outcome.get("business_description"),
                        "source": "web_research",
                        "confidence": outcome.get("confidence"),
                        "sources": outcome.get("sources") or [],
                        "status": DataStatus.LIVE.value,
                    }
                )
        self._store(canonical, "profile", payload)
        return payload

    def _fundamentals(self, canonical: str) -> dict:
        cached = self._cached(canonical, "fundamentals", TTL_FUNDAMENTALS_SECONDS)
        if cached is not None:
            return cached
        try:
            coverage = self.fundamentals_service.get_coverage(canonical)
        except Exception as exc:
            logger.warning("Fundamentals read failed for %s: %s", canonical, type(exc).__name__)
            payload = {
                "status": DataStatus.ERROR.value,
                "metric_count": 0,
                "metrics": {},
                "available": False,
                "error": f"{type(exc).__name__}",
            }
            self._store(canonical, "fundamentals", payload)
            return payload
        coverage["available"] = coverage["metric_count"] > 0
        if coverage["metric_count"] == 0:
            coverage["status"] = DataStatus.UNAVAILABLE.value
            coverage["note"] = (
                "No fundamentals stored for this symbol. Ingested official "
                "filings are the primary source; a provider fundamentals "
                "refresh is unavailable and no web-research enrichment has "
                "been run."
            )
        self._store(canonical, "fundamentals", coverage)
        return coverage

    def _news(self, canonical: str) -> dict:
        cached = self._cached(canonical, "news", TTL_NEWS_SECONDS)
        if cached is not None:
            return cached
        try:
            articles = self.news_repo.get_articles(canonical, limit=20)
        except Exception as exc:
            logger.warning("News read failed for %s: %s", canonical, type(exc).__name__)
            payload = {
                "status": DataStatus.ERROR.value,
                "count": 0,
                "articles": [],
                "available": False,
                "error": f"{type(exc).__name__}",
            }
            self._store(canonical, "news", payload)
            return payload
        payload = {
            "status": DataStatus.CACHED.value if articles else DataStatus.UNAVAILABLE.value,
            "count": len(articles),
            "articles": articles,
            "available": bool(articles),
            "note": None
            if articles
            else "No stored news for this symbol yet — news refresh is an explicit action.",
        }
        self._store(canonical, "news", payload)
        return payload
