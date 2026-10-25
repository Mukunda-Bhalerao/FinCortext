"""Upstox REST client: OAuth exchange, quotes, candles and the instrument master.

Endpoints and response shapes follow the official Upstox developer documentation:
- OAuth:  /v2/login/authorization/dialog, /v2/login/authorization/token
- Quotes: /v2/market-quote/quotes (max 500 keys; data keyed by "SEGMENT:SYMBOL",
          each entry carries its instrument key in ``instrument_token``)
- Candles: /v3/historical-candle/{key}/{unit}/{interval}/{to}/{from}
           /v3/historical-candle/intraday/{key}/{unit}/{interval}
- Instruments: https://assets.upstox.com/market-quote/instruments/exchange/{EXCHANGE}.json.gz
"""

import asyncio
import gzip
import json
import logging
import time
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any
from urllib.parse import quote, urlencode

import httpx

from app.errors import (
    NotConnected,
    ProviderRequestError,
    ProviderUnavailable,
    RateLimited,
    TokenInvalid,
)
from app.providers.base import InstrumentRecord, Profile, ProviderQuote
from app.schemas.market import Candle
from app.tools.candles import parse_candle_rows

log = logging.getLogger(__name__)

API_BASE = "https://api.upstox.com"
AUTH_DIALOG_URL = f"{API_BASE}/v2/login/authorization/dialog"
TOKEN_URL = f"{API_BASE}/v2/login/authorization/token"
INSTRUMENTS_URL = "https://assets.upstox.com/market-quote/instruments/exchange/{exchange}.json.gz"
FEED_AUTHORIZE_URL = f"{API_BASE}/v3/feed/market-data-feed/authorize"
FEED_URL = "wss://api.upstox.com/v3/feed/market-data-feed"

MAX_QUOTE_KEYS = 500
# Instrument types kept from the master: cash-market equities and indices.
_EQUITY_TYPES = {"EQ", "BE", "SM", "ST"}
_INDEX_SEGMENTS = {"NSE_INDEX", "BSE_INDEX"}

TokenGetter = Callable[[], str | None]


def authorization_url(api_key: str, redirect_uri: str, state: str) -> str:
    params = {
        "response_type": "code",
        "client_id": api_key,
        "redirect_uri": redirect_uri,
        "state": state,
    }
    return f"{AUTH_DIALOG_URL}?{urlencode(params)}"


class _RateLimiter:
    """Spaces request starts and caps concurrency. Upstox enforces per-second limits."""

    def __init__(self, per_second: float, concurrency: int):
        self._spacing = 1.0 / per_second
        self._next = 0.0
        self._lock = asyncio.Lock()
        self._sem = asyncio.Semaphore(concurrency)

    async def __aenter__(self) -> None:
        await self._sem.acquire()
        async with self._lock:
            now = time.monotonic()
            wait = self._next - now
            self._next = max(now, self._next) + self._spacing
        if wait > 0:
            await asyncio.sleep(wait)

    async def __aexit__(self, *exc: object) -> None:
        self._sem.release()


def _error_detail(resp: httpx.Response) -> tuple[str | None, str]:
    try:
        body = resp.json()
        err = (body.get("errors") or [{}])[0]
        return err.get("errorCode") or err.get("error_code"), err.get(
            "message"
        ) or resp.reason_phrase
    except (ValueError, AttributeError):
        return None, resp.reason_phrase


def _num(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _ms_to_dt(value: Any) -> datetime | None:
    try:
        ms = int(value)
    except (TypeError, ValueError):
        return None
    if ms <= 0:
        return None
    return datetime.fromtimestamp(ms / 1000, tz=UTC)


def parse_quotes(payload: dict[str, Any]) -> dict[str, ProviderQuote]:
    """Normalize a /v2/market-quote/quotes response, keyed by instrument key."""
    out: dict[str, ProviderQuote] = {}
    for entry in (payload.get("data") or {}).values():
        key = entry.get("instrument_token")
        if not key:
            continue
        ltp = _num(entry.get("last_price"))
        net_change = _num(entry.get("net_change"))
        prev_close = ltp - net_change if ltp is not None and net_change is not None else None
        ohlc = entry.get("ohlc") or {}
        volume = entry.get("volume")
        out[key] = ProviderQuote(
            instrument_key=key,
            symbol=entry.get("symbol"),
            ltp=ltp if ltp and ltp > 0 else None,
            prev_close=round(prev_close, 4) if prev_close and prev_close > 0 else None,
            open=_num(ohlc.get("open")) or None,
            high=_num(ohlc.get("high")) or None,
            low=_num(ohlc.get("low")) or None,
            volume=int(volume) if volume else None,
            avg_price=_num(entry.get("average_price")) or None,
            upper_circuit=_num(entry.get("upper_circuit_limit")) or None,
            lower_circuit=_num(entry.get("lower_circuit_limit")) or None,
            last_trade_time=_ms_to_dt(entry.get("last_trade_time")),
        )
    return out


def parse_instruments(rows: list[dict[str, Any]]) -> list[InstrumentRecord]:
    out: list[InstrumentRecord] = []
    for r in rows:
        segment = r.get("segment")
        itype = r.get("instrument_type")
        is_equity = segment == "NSE_EQ" and itype in _EQUITY_TYPES
        is_index = segment in _INDEX_SEGMENTS and itype == "INDEX"
        if not (is_equity or is_index) or not r.get("instrument_key"):
            continue
        out.append(
            InstrumentRecord(
                instrument_key=r["instrument_key"],
                segment=segment,
                exchange=r.get("exchange") or segment.split("_")[0],
                instrument_type=itype,
                trading_symbol=r.get("trading_symbol") or "",
                name=r.get("name"),
                short_name=r.get("short_name"),
                isin=r.get("isin"),
                exchange_token=r.get("exchange_token"),
                lot_size=r.get("lot_size"),
                tick_size=r.get("tick_size"),
            )
        )
    return out


class UpstoxProvider:
    name = "upstox"

    def __init__(self, token_getter: TokenGetter, on_token_rejected: Callable[[str], None]):
        self._token = token_getter
        self._on_token_rejected = on_token_rejected
        self._client = httpx.AsyncClient(
            base_url=API_BASE,
            timeout=httpx.Timeout(10.0, connect=5.0),
            headers={"Accept": "application/json"},
        )
        self._limiter = _RateLimiter(per_second=20, concurrency=6)

    async def aclose(self) -> None:
        await self._client.aclose()

    # --- transport ---------------------------------------------------------------

    async def _get(
        self, path: str, params: dict[str, str] | None = None, *, reject_on_401: bool = True
    ) -> dict[str, Any]:
        """GET with retries. A 401 marks the token rejected unless the endpoint is outside
        the token's scope (``reject_on_401=False``), e.g. account APIs for read-only tokens."""
        token = self._token()
        if not token:
            raise NotConnected("Upstox is not connected. Connect your account to load market data.")
        headers = {"Authorization": f"Bearer {token}"}
        attempts = 3
        for attempt in range(attempts):
            try:
                async with self._limiter:
                    resp = await self._client.get(path, params=params, headers=headers)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                if attempt == attempts - 1:
                    raise ProviderUnavailable(
                        "Upstox did not respond. Check your network connection."
                    ) from exc
                await asyncio.sleep(0.5 * 2**attempt)
                continue

            if resp.status_code == 200:
                return resp.json()
            code, message = _error_detail(resp)
            if resp.status_code == 401 and not reject_on_401:
                raise ProviderRequestError("Not permitted for this Upstox token.", code=code)
            if resp.status_code == 401:
                self._on_token_rejected(code or "401")
                raise TokenInvalid("Upstox session expired or was revoked. Reconnect Upstox.")
            if resp.status_code == 429 or resp.status_code >= 500:
                if attempt < attempts - 1:
                    retry_after = _num(resp.headers.get("Retry-After")) or 0.5 * 2**attempt
                    await asyncio.sleep(min(retry_after, 5.0))
                    continue
                if resp.status_code == 429:
                    raise RateLimited("Upstox rate limit reached. Data will refresh shortly.")
                raise ProviderUnavailable(
                    f"Upstox is temporarily unavailable ({resp.status_code})."
                )
            log.info("upstox rejected %s: %s %s", path.split("/")[2], code, message)
            raise ProviderRequestError(f"Upstox rejected the request: {message}", code=code)
        raise ProviderUnavailable("Upstox request failed.")

    # --- auth ----------------------------------------------------------------------

    @staticmethod
    async def exchange_code(
        code: str, api_key: str, api_secret: str, redirect_uri: str
    ) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                resp = await client.post(
                    TOKEN_URL,
                    data={
                        "code": code,
                        "client_id": api_key,
                        "client_secret": api_secret,
                        "redirect_uri": redirect_uri,
                        "grant_type": "authorization_code",
                    },
                    headers={"Accept": "application/json"},
                )
            except httpx.HTTPError as exc:
                raise ProviderUnavailable("Could not reach Upstox to complete sign-in.") from exc
        if resp.status_code != 200:
            _, message = _error_detail(resp)
            raise ProviderRequestError(f"Upstox sign-in failed: {message}")
        body = resp.json()
        if not body.get("access_token"):
            raise ProviderRequestError("Upstox sign-in returned no access token.")
        return body

    async def get_profile(self) -> Profile:
        # Analytics (read-only) tokens cannot call User APIs without a whitelisted static IP.
        body = await self._get("/v2/user/profile", reject_on_401=False)
        data = body.get("data") or {}
        return Profile(user_id=data.get("user_id"), user_name=data.get("user_name"))

    # --- market data -------------------------------------------------------------

    async def get_quotes(self, instrument_keys: list[str]) -> dict[str, ProviderQuote]:
        out: dict[str, ProviderQuote] = {}
        for i in range(0, len(instrument_keys), MAX_QUOTE_KEYS):
            batch = instrument_keys[i : i + MAX_QUOTE_KEYS]
            body = await self._get(
                "/v2/market-quote/quotes", params={"instrument_key": ",".join(batch)}
            )
            out.update(parse_quotes(body))
        return out

    async def get_historical_candles(
        self, instrument_key: str, unit: str, interval: int, to_date: date, from_date: date
    ) -> list[Candle]:
        path = (
            f"/v3/historical-candle/{quote(instrument_key, safe='')}/{unit}/{interval}"
            f"/{to_date.isoformat()}/{from_date.isoformat()}"
        )
        body = await self._get(path)
        return parse_candle_rows((body.get("data") or {}).get("candles") or [])

    async def get_intraday_candles(
        self, instrument_key: str, unit: str, interval: int
    ) -> list[Candle]:
        path = f"/v3/historical-candle/intraday/{quote(instrument_key, safe='')}/{unit}/{interval}"
        body = await self._get(path)
        return parse_candle_rows((body.get("data") or {}).get("candles") or [])

    async def get_market_status(self, exchange: str) -> str | None:
        """Exchange session status, e.g. NORMAL_OPEN / NORMAL_CLOSE (Market Status appendix)."""
        body = await self._get(f"/v2/market/status/{exchange}")
        return (body.get("data") or {}).get("status")

    async def get_feed_url(self) -> str:
        body = await self._get("/v3/feed/market-data-feed/authorize")
        url = (body.get("data") or {}).get("authorized_redirect_uri")
        if not url:
            raise ProviderUnavailable("Upstox did not return a market data feed URL.")
        return url

    # --- reference data (public files, no token required) ------------------------

    async def fetch_instruments(self) -> list[InstrumentRecord]:
        records: list[InstrumentRecord] = []
        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0)) as client:
            for exchange in ("NSE", "BSE"):
                resp = await client.get(INSTRUMENTS_URL.format(exchange=exchange))
                resp.raise_for_status()
                rows = json.loads(gzip.decompress(resp.content))
                records.extend(parse_instruments(rows))
        return records
