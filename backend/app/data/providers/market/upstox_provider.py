"""Upstox market provider: Upstox Analytics -> canonical FinCortext models.

Implements the existing ``MarketDataProvider`` contract so the rest of the
pipeline (validation -> MarketRepository/DuckDB -> analysts -> frontend) never
sees Upstox internals:

Upstox API -> UpstoxMarketProvider -> MarketService/Repository -> DuckDB

- Search filters to NSE equity (exchange=NSE, segment=EQ) and uses the
  Upstox ``instrument_key`` as the canonical API identifier.
- Quotes are normalized with explicit ``None`` for genuinely missing fields
  (never 0 or fabricated values) so the frontend can render "N/A".
- History normalizes V3 daily candles into canonical ``MarketPrice`` bars
  with ``source_type=upstox``.
- An optional yfinance fallback provider keeps research working when Upstox
  fails; fallback bars are clearly marked ``source_type=yfinance``.
- The access token is never logged, never included in errors, and never
  returned in payloads.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from app.core.exceptions import ProviderError, ProviderUnavailableError
from app.core.logging import get_logger
from app.data.providers.market.upstox_client import UpstoxHttpClient
from app.domain.contracts.providers import MarketDataProvider
from app.domain.models.base import DataSourceType
from app.domain.models.market import MarketPrice

logger = get_logger("providers.upstox")


def _is_nse_equity(item: dict) -> bool:
    if not isinstance(item, dict):
        return False
    if (item.get("exchange") or "").upper() != "NSE":
        return False
    segment = (item.get("segment") or "").upper()  # e.g. "NSE_EQ"
    itype = (item.get("instrument_type") or "").upper()  # e.g. "EQ"
    # NSE_EQ also lists corporate bonds (instrument_type N0, ...): only the
    # EQ series is a tradeable equity. When instrument_type is absent, fall
    # back to the segment check.
    if itype:
        return itype == "EQ"
    return segment == "NSE_EQ"


def normalize_search_item(item: dict) -> dict:
    """Normalize one raw Upstox EQ search row to FinCortext fields."""
    trading = str(item.get("trading_symbol") or "").strip()
    return {
        "symbol": trading.upper(),
        "trading_symbol": trading,
        "name": str(item.get("name") or trading or "").strip(),
        "instrument_key": str(item.get("instrument_key") or "").strip(),
        "exchange": str(item.get("exchange") or "NSE").strip().upper(),
        "segment": "EQ",
        "raw_segment": str(item.get("segment") or "").strip(),
        "isin": str(item.get("isin") or "").strip() or None,
        "exchange_token": str(item.get("exchange_token") or "").strip() or None,
        "instrument_type": str(item.get("instrument_type") or "").strip() or None,
        "tick_size": item.get("tick_size"),
        "lot_size": item.get("lot_size"),
    }


def pick_best_equity(items: list[dict], query: str) -> dict | None:
    """Pick the best NSE equity for ``query``: exact trading_symbol first."""
    equities = [it for it in items if _is_nse_equity(it)]
    if not equities:
        return None
    q = (query or "").strip().upper()
    # Strip a trailing ".NS" so "TCS.NS" still exact-matches "TCS".
    q_base = q[:-3] if q.endswith(".NS") else q
    for it in equities:
        ts = str(it.get("trading_symbol") or "").strip().upper()
        if ts and (ts == q or ts == q_base):
            return it
    # Prefer the shortest trading symbol containing the query (avoids
    # picking "RELIANCE FUT ..." style rows if any slip through).
    def _rank(it: dict) -> tuple:
        ts = str(it.get("trading_symbol") or "").upper()
        contains = 0 if q_base and q_base in ts else 1
        return (contains, len(ts), ts)

    return sorted(equities, key=_rank)[0]


def _num(value: Any) -> float | None:
    if value is None:
        return None
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    # NaN / inf are not real market values.
    if num != num or num in (float("inf"), float("-inf")):
        return None
    return num


def normalize_quote(raw: dict, *, instrument_key: str, fallback_symbol: str = "") -> dict:
    """Normalize one raw V3 full-quote object.

    Field names are snake_case and stable — the frontend mirrors them exactly
    so valid Upstox values never become null through a rename. Missing values
    stay ``None`` (never 0).
    """
    ohlc = raw.get("ohlc") if isinstance(raw.get("ohlc"), dict) else {}
    last_price = _num(raw.get("last_price"))
    prev_close = _num(raw.get("prev_close_price"))
    open_p = _num(ohlc.get("open"))
    high_p = _num(ohlc.get("high"))
    low_p = _num(ohlc.get("low"))
    close_p = _num(ohlc.get("close"))
    volume = _num(raw.get("volume"))
    if volume is None:
        volume = _num(ohlc.get("volume"))
    avg_price = _num(raw.get("average_price"))
    year_high = _num(raw.get("year_high"))
    year_low = _num(raw.get("year_low"))
    symbol = str(raw.get("symbol") or fallback_symbol or "").strip().upper()
    day_change = None
    day_change_pct = None
    if last_price is not None and prev_close is not None and prev_close:
        day_change = last_price - prev_close
        day_change_pct = (day_change / prev_close) * 100.0
    return {
        "symbol": symbol,
        "instrument_key": str(raw.get("instrument_token") or instrument_key or "").strip(),
        "trading_symbol": str(raw.get("symbol") or fallback_symbol or "").strip(),
        "exchange": "NSE",
        "segment": "EQ",
        "source": "upstox",
        "timestamp": raw.get("timestamp"),
        "last_price": last_price,
        "prev_close": prev_close,
        "open": open_p,
        "high": high_p,
        "low": low_p,
        "close": close_p,
        "volume": volume,
        "average_price": avg_price,
        "year_high": year_high,
        "year_low": year_low,
        "day_change": day_change,
        "day_change_pct": day_change_pct,
    }


def _candle_date(ts_raw: Any) -> date | None:
    try:
        text = str(ts_raw)
        # "2025-01-01T00:00:00+05:30" -> date; also accepts "YYYY-MM-DD".
        if "T" in text:
            dt = datetime.fromisoformat(text)
            return dt.date()
        return date.fromisoformat(text[:10])
    except Exception:
        return None


class UpstoxMarketProvider(MarketDataProvider):
    """MarketDataProvider backed by Upstox Analytics (NSE equity)."""

    name = "upstox"

    def __init__(
        self,
        access_token: str,
        *,
        base_url: str = "https://api.upstox.com",
        timeout_seconds: int = 10,
        symbol_to_instrument: dict[str, str] | None = None,
        fallback: MarketDataProvider | None = None,
        client: UpstoxHttpClient | None = None,
    ) -> None:
        self._client = client or UpstoxHttpClient(
            access_token, base_url=base_url, timeout_seconds=timeout_seconds
        )
        # Canonical symbol (upper) -> instrument_key.
        self._key_cache: dict[str, str] = {
            str(k).upper(): str(v) for k, v in (symbol_to_instrument or {}).items() if v
        }
        # instrument_key -> normalized search metadata.
        self._meta_cache: dict[str, dict] = {}
        self._fallback = fallback

    @property
    def is_configured(self) -> bool:
        return self._client.is_configured

    # -- search / resolve ----------------------------------------------------

    def search_equity(self, query: str, *, records: int = 20) -> list[dict]:
        """Search Upstox and return normalized NSE equity instruments."""
        payload = self._client.search_instruments(query, exchanges="NSE", segments="EQ", records=records)
        items = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(items, list):
            raise ProviderError(
                "Upstox search returned malformed data.",
                details={"provider": self.name},
            )
        out: list[dict] = []
        for raw in items:
            if not _is_nse_equity(raw if isinstance(raw, dict) else {}):
                continue
            norm = normalize_search_item(raw)
            if not norm["instrument_key"] or not norm["symbol"]:
                continue
            out.append(norm)
            self._meta_cache[norm["instrument_key"]] = norm
            self._key_cache[norm["symbol"]] = norm["instrument_key"]
        return out

    def resolve_equity(self, query: str) -> dict:
        """Resolve one NSE equity for ``query`` (raises when none found)."""
        results = self.search_equity(query)
        if not results:
            raise ProviderError(
                f"No NSE equity found on Upstox for '{query}'.",
                details={"provider": self.name, "query": query},
            )
        # Re-run the pick on raw-equivalent normalized rows: exact symbol wins.
        q = (query or "").strip().upper()
        q_base = q[:-3] if q.endswith(".NS") else q
        for row in results:
            if row["symbol"] == q or row["symbol"] == q_base:
                return row
        return results[0]

    def _resolve_key(self, symbol: str) -> tuple[str, str]:
        """Return (canonical_symbol, instrument_key), searching when needed."""
        canonical = (symbol or "").strip().upper().replace(".NS", "") if symbol.strip().upper().endswith(".NS") else (symbol or "").strip().upper()
        # Direct instrument key passed?
        if "|" in symbol:
            return canonical, symbol.strip()
        cached = self._key_cache.get(canonical)
        if cached:
            return canonical, cached
        resolved = self.resolve_equity(canonical)
        self._key_cache[canonical] = resolved["instrument_key"]
        return canonical, resolved["instrument_key"]

    def cache_instrument(self, meta: dict) -> None:
        """Seed the resolver cache (used by resolve/select flows)."""
        key = str(meta.get("instrument_key") or "").strip()
        sym = str(meta.get("symbol") or meta.get("trading_symbol") or "").strip().upper()
        if key and sym:
            self._key_cache[sym] = key
            self._meta_cache[key] = meta

    # -- quotes ----------------------------------------------------------------

    def fetch_quote_by_key(self, instrument_key: str, *, symbol_hint: str = "") -> dict:
        data = self._client.fetch_full_quotes([instrument_key])
        # Keyed by "NSE_EQ:TRADING" (or instrument key with colon); take match
        # or first entry — never fabricate when empty.
        raw = None
        for _k, v in data.items():
            if not isinstance(v, dict):
                continue
            token = str(v.get("instrument_token") or "")
            if token == instrument_key:
                raw = v
                break
        if raw is None:
            for v in data.values():
                if isinstance(v, dict):
                    raw = v
                    break
        if raw is None:
            raise ProviderError(
                "Upstox quote response contained no usable quote.",
                details={"provider": self.name},
            )
        return normalize_quote(raw, instrument_key=instrument_key, fallback_symbol=symbol_hint)

    def fetch_quote_for_symbol(self, symbol: str) -> dict:
        canonical, key = self._resolve_key(symbol)
        return self.fetch_quote_by_key(key, symbol_hint=canonical)

    # -- history (MarketDataProvider contract) -----------------------------------

    def fetch_ohlcv_by_key(
        self, symbol: str, instrument_key: str, start: date, end: date
    ) -> list[MarketPrice]:
        canonical = (symbol or "").strip().upper()
        candles = self._client.fetch_daily_candles(instrument_key, start, end)
        bars: list[MarketPrice] = []
        for candle in candles:
            if not isinstance(candle, (list, tuple)) or len(candle) < 6:
                continue
            ts_raw, o, h, low, c, vol = candle[0], candle[1], candle[2], candle[3], candle[4], candle[5]
            trade_date = _candle_date(ts_raw)
            o_f, h_f, l_f, c_f = _num(o), _num(h), _num(low), _num(c)
            if trade_date is None or o_f is None or h_f is None or l_f is None or c_f is None:
                continue
            if min(o_f, h_f, l_f, c_f) <= 0:
                continue
            v_f = _num(vol)
            try:
                bars.append(
                    MarketPrice(
                        symbol=canonical,
                        exchange="NSE",
                        provider_ticker=instrument_key,
                        trade_date=trade_date,
                        open=float(o_f),
                        high=float(h_f),
                        low=float(l_f),
                        close=float(c_f),
                        volume=float(v_f) if v_f is not None and v_f >= 0 else 0.0,
                        currency="INR",
                        source_type=DataSourceType.UPSTOX,
                        source_name="upstox",
                    )
                )
            except Exception as exc:  # skip malformed single rows, keep visible
                logger.warning("Skipping malformed Upstox candle for %s: %s", canonical, type(exc).__name__)
        bars.sort(key=lambda b: b.trade_date)
        return bars

    def fetch_ohlcv(self, ticker: str, start: date, end: date) -> list[MarketPrice]:
        """Fetch daily OHLCV for a canonical symbol (or instrument key).

        On Upstox failure the configured yfinance fallback is tried and its
        bars (clearly marked yfinance) are returned; nothing is fabricated.
        """
        try:
            if "|" in (ticker or ""):
                # Direct key: canonical symbol unknown — resolve via quote meta
                # when possible, else key the bars by the upper-cased hint.
                key = ticker.strip()
                hint = self._meta_cache.get(key, {}).get("symbol", "")
                if not hint:
                    try:
                        q = self.fetch_quote_by_key(key)
                        hint = q.get("symbol") or ""
                        if hint:
                            self._key_cache[hint] = key
                    except Exception:
                        hint = ""
                canonical = (hint or key).upper()
                return self.fetch_ohlcv_by_key(canonical, key, start, end)
            canonical, key = self._resolve_key(ticker)
            return self.fetch_ohlcv_by_key(canonical, key, start, end)
        except (ProviderError, ProviderUnavailableError) as exc:
            if self._fallback is None:
                raise
            logger.warning(
                "Upstox history failed for %s (%s); trying yfinance fallback",
                ticker, type(exc).__name__,
            )
            # Fallback bars carry their own yfinance provenance.
            return self._fallback.fetch_ohlcv(ticker, start, end)
