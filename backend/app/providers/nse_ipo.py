"""NSE public IPO data: issues open now, announced issues, the past-issue register and
per-issue details (subscription by investor category, price band, lot, lead managers).

The nseindia.com JSON endpoints answer only to a browser-like session: a page is loaded
first to receive cookies, and the session is renewed when NSE starts refusing it.
"""

import asyncio
import time
from typing import Any

import httpx

from app.errors import ProviderUnavailable
from app.providers import fetch

BASE = "https://www.nseindia.com"
WARMUP = f"{BASE}/market-data/all-upcoming-issues-ipo"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like "
    "Gecko) Chrome/130.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-IN,en;q=0.9",
    "Referer": WARMUP,
}
SESSION_TTL = 15 * 60  # seconds before the cookies are refreshed
MIN_GAP = 0.6  # seconds between requests: NSE throttles bursts


class NseIpoClient:
    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None
        self._warmed_at = 0.0
        self._lock = asyncio.Lock()
        self._last_call = 0.0

    async def _session(self, renew: bool = False) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=20.0, headers=_HEADERS, follow_redirects=True)
        if renew or time.monotonic() - self._warmed_at > SESSION_TTL:
            self._client.cookies.clear()
            await fetch.get(self._client, WARMUP)
            self._warmed_at = time.monotonic()
        return self._client

    async def _json(self, path: str) -> Any:
        async with self._lock:
            for attempt in (0, 1):
                gap = MIN_GAP - (time.monotonic() - self._last_call)
                if gap > 0:
                    await asyncio.sleep(gap)
                try:
                    client = await self._session(renew=attempt == 1)
                    resp = await fetch.get(client, BASE + path)
                except httpx.HTTPError as exc:
                    raise ProviderUnavailable(
                        f"NSE did not answer ({type(exc).__name__})."
                    ) from exc
                finally:
                    self._last_call = time.monotonic()
                if resp.status_code in (401, 403) and attempt == 0:
                    continue  # session expired: warm up again
                if resp.status_code != 200:
                    raise ProviderUnavailable(f"NSE answered {resp.status_code} for IPO data.")
                try:
                    return resp.json()
                except ValueError as exc:
                    if attempt == 0:
                        continue  # an HTML block page instead of JSON: renew once
                    raise ProviderUnavailable("NSE sent a page instead of IPO data.") from exc
        raise ProviderUnavailable("NSE refused the IPO data request.")

    async def current(self) -> list[dict]:
        return _rows(await self._json("/api/ipo-current-issue"))

    async def upcoming(self) -> list[dict]:
        return _rows(await self._json("/api/all-upcoming-issues?category=ipo"))

    async def past(self) -> list[dict]:
        return _rows(await self._json("/api/public-past-issues"))

    async def detail(self, symbol: str, series: str = "EQ") -> dict:
        data = await self._json(f"/api/ipo-detail?symbol={symbol}&series={series}")
        if not isinstance(data, dict):
            raise ProviderUnavailable(f"NSE has no IPO details for {symbol}.")
        return data

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()


def _rows(data: Any) -> list[dict]:
    if isinstance(data, list):
        return [r for r in data if isinstance(r, dict)]
    if isinstance(data, dict):
        for key in ("data", "rows", "upcoming"):
            if isinstance(data.get(key), list):
                return [r for r in data[key] if isinstance(r, dict)]
    return []
