"""Low-level Upstox Analytics HTTP client.

Wraps the three official endpoints FinCortext needs:
- Instrument Search API  (GET /v2/instruments/search)
- Full Market Quotes V3   (GET /v3/market-quote/quotes)
- Historical Candle V3    (GET /v3/historical-candle/{key}/days/1/{to}/{from})

The access token is taken from configuration only and is NEVER written to
logs, errors, or responses. Authentication failures (HTTP 401/403) surface as
ProviderUnavailableError so callers can degrade honestly; every other failure
surfaces as ProviderError. No fabrication anywhere.
"""

from __future__ import annotations

from datetime import date
from typing import Any
from urllib.parse import quote as urlquote

import requests

from app.core.exceptions import ProviderError, ProviderUnavailableError
from app.core.logging import get_logger

logger = get_logger("providers.upstox.client")


def _safe_detail(status: int, body_snippet: str) -> dict:
    return {"provider": "upstox", "http_status": status, "body": body_snippet[:500]}


class UpstoxHttpClient:
    """Thin authenticated HTTP wrapper for Upstox Analytics APIs."""

    def __init__(
        self,
        access_token: str,
        base_url: str = "https://api.upstox.com",
        timeout_seconds: int = 10,
    ) -> None:
        self._token = (access_token or "").strip()
        self._base = (base_url or "https://api.upstox.com").rstrip("/")
        self._timeout = max(1, int(timeout_seconds or 10))

    @property
    def is_configured(self) -> bool:
        return bool(self._token)

    def _headers(self) -> dict[str, str]:
        return {
            "Accept": "application/json",
            "Content-Type": "application/json",
            # Token is only ever placed in the Authorization header.
            "Authorization": f"Bearer {self._token}",
        }

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict:
        if not self.is_configured:
            raise ProviderUnavailableError(
                "UPSTOX_ACCESS_TOKEN is not configured — Upstox data unavailable.",
                details={"provider": "upstox"},
            )
        url = f"{self._base}{path}"
        try:
            resp = requests.get(url, headers=self._headers(), params=params or {}, timeout=self._timeout)
        except requests.Timeout as exc:
            raise ProviderError(
                f"Upstox request timed out ({path})",
                details={"provider": "upstox", "path": path},
            ) from exc
        except Exception as exc:  # network / DNS / TLS, never leak token
            raise ProviderError(
                f"Upstox request failed ({path}): {type(exc).__name__}",
                details={"provider": "upstox", "path": path},
            ) from exc

        if resp.status_code in (401, 403):
            # Never include the token or raw body beyond a short snippet.
            logger.warning("Upstox authentication failed (HTTP %s)", resp.status_code)
            raise ProviderUnavailableError(
                "Upstox authentication failed — check UPSTOX_ACCESS_TOKEN.",
                details=_safe_detail(resp.status_code, resp.text or ""),
            )
        if resp.status_code == 429:
            raise ProviderError(
                "Upstox rate limit exceeded — retry later.",
                details=_safe_detail(resp.status_code, resp.text or ""),
            )
        if resp.status_code < 200 or resp.status_code >= 300:
            raise ProviderError(
                f"Upstox request failed with HTTP {resp.status_code}",
                details=_safe_detail(resp.status_code, resp.text or ""),
            )
        try:
            payload = resp.json()
        except Exception as exc:
            raise ProviderError(
                "Upstox returned a non-JSON response.",
                details={"provider": "upstox", "path": path},
            ) from exc
        return payload

    # -- public endpoints ---------------------------------------------------

    def search_instruments(
        self,
        query: str,
        *,
        exchanges: str = "NSE",
        segments: str = "EQ",
        page_number: int = 1,
        records: int = 20,
    ) -> dict:
        """Instrument Search API. Returns the raw decoded JSON payload."""
        q = (query or "").strip()
        if not q:
            raise ProviderError(
                "Upstox instrument search requires a non-empty query.",
                details={"provider": "upstox"},
            )
        payload = self._get(
            "/v2/instruments/search",
            params={
                "query": q[:50],
                "exchanges": exchanges or "NSE",
                "segments": segments or "EQ",
                "page_number": max(1, int(page_number or 1)),
                "records": min(30, max(1, int(records or 20))),
            },
        )
        if not isinstance(payload, dict) or payload.get("status") != "success":
            raise ProviderError(
                "Upstox instrument search returned an unexpected payload.",
                details={"provider": "upstox"},
            )
        return payload

    def fetch_full_quotes(self, instrument_keys: list[str]) -> dict:
        """Full Market Quotes V3 for up to 500 instrument keys.

        Returns the raw ``data`` object keyed by Upstox (e.g. ``NSE_EQ:RELIANCE``).
        """
        keys = [k.strip() for k in (instrument_keys or []) if k and k.strip()]
        if not keys:
            raise ProviderError(
                "Upstox quote request requires at least one instrument key.",
                details={"provider": "upstox"},
            )
        if len(keys) > 500:
            keys = keys[:500]
        payload = self._get(
            "/v3/market-quote/quotes",
            params={"instrument_key": ",".join(keys)},
        )
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, dict):
            raise ProviderError(
                "Upstox quote response had no data object.",
                details={"provider": "upstox"},
            )
        return data

    def fetch_daily_candles(
        self, instrument_key: str, start: date, end: date
    ) -> list[list]:
        """Historical Candle V3 (unit=days, interval=1).

        Returns the raw ``candles`` list: each candle is
        [timestamp_iso, open, high, low, close, volume, oi].
        """
        key = (instrument_key or "").strip()
        if not key:
            raise ProviderError(
                "Upstox candle request requires an instrument key.",
                details={"provider": "upstox"},
            )
        if end < start:
            raise ProviderError(
                "Upstox candle request needs start <= end.",
                details={"provider": "upstox"},
            )
        encoded = urlquote(key, safe="")
        path = (
            f"/v3/historical-candle/{encoded}/days/1/"
            f"{end.isoformat()}/{start.isoformat()}"
        )
        payload = self._get(path)
        data = payload.get("data") if isinstance(payload, dict) else None
        candles = data.get("candles") if isinstance(data, dict) else None
        if candles is None:
            raise ProviderError(
                "Upstox candle response had no candles.",
                details={"provider": "upstox"},
            )
        if not isinstance(candles, list):
            raise ProviderError(
                "Upstox candle response had malformed candles.",
                details={"provider": "upstox"},
            )
        return candles
