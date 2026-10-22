"""Market Dashboard service: one assembly for the Indian market overview.

Assembles ONLY real, live-verified Upstox data plus stored analyst outputs:

- indices: Nifty 50, Nifty Bank, Nifty IT, India VIX — daily candles
  (Historical Candle V3, verified working for NSE_INDEX keys) give the day
  change (last close vs previous close) and the recent series; a batched
  Full Market Quotes V3 call supersedes the current level when the market
  is open. Index candles are ephemeral-by-day, cached for 5 minutes.
- movers: top gainers/losers among TRACKED companies (the curated universe
  plus registered dynamic equities) from one batched live-quotes call,
  sorted by day change percentage. Never a whole-market ranking — the
  label says exactly what the ranking covers.
- opportunities: the latest stored analyst outputs per company, ranked by
  score — every entry traces back to a real stored AgentOutput.

Nothing is fabricated: unavailable indices/movers degrade to explicit
statuses; no ranking is invented for symbols without real quotes.
"""

from __future__ import annotations

from datetime import date, timedelta

from app.core.exceptions import ProviderError, ProviderUnavailableError
from app.core.logging import get_logger
from app.data.providers.market.upstox_client import UpstoxHttpClient
from app.data.providers.market.upstox_provider import _candle_date, _num, normalize_quote
from app.domain.models.base import DataStatus

logger = get_logger("services.market_dashboard")

INDEX_DEFS: list[dict] = [
    {"key": "NSE_INDEX|Nifty 50", "name": "Nifty 50", "chart": True},
    {"key": "NSE_INDEX|Nifty Bank", "name": "Nifty Bank", "chart": False},
    {"key": "NSE_INDEX|Nifty IT", "name": "Nifty IT", "chart": False},
    {"key": "NSE_INDEX|India VIX", "name": "India VIX", "chart": False},
]

INDEX_TTL_SECONDS = 300          # index candles: 5 minutes
MOVERS_TTL_SECONDS = 60          # movers from live quotes: 1 minute
OPPORTUNITIES_TTL_SECONDS = 600  # stored analyst outputs: 10 minutes
INDEX_CANDLE_DAYS = 45
MOVER_LIMIT = 5


def _fresh(stamp: float, ttl: int, now: float) -> bool:
    return (now - stamp) < ttl


class MarketDashboardService:
    """Assembles the Indian market overview (indices, movers, opportunities)."""

    def __init__(
        self,
        *,
        upstox_client: UpstoxHttpClient,
        market_repo,
        instrument_repo,
        agent_output_repo,
        universe_entries,
    ):
        self._client = upstox_client
        self.market_repo = market_repo
        self.instrument_repo = instrument_repo
        self.agent_output_repo = agent_output_repo
        self._universe_entries = universe_entries
        self._index_cache: dict | None = None
        self._index_cache_at: float = 0.0
        self._movers_cache: dict | None = None
        self._movers_cache_at: float = 0.0
        self._opps_cache: dict | None = None
        self._opps_cache_at: float = 0.0

    # -- public ----------------------------------------------------------------

    def get_dashboard(self) -> dict:
        import time as _time

        now = _time.time()
        indices = self._indices(now)
        movers = self._movers(now)
        opportunities = self._opportunities(now)
        return {
            "indices": indices,
            "movers": movers,
            "opportunities": opportunities,
            "tracked_count": self._tracked_symbols(),
            "as_of": _utcnow_iso(),
        }

    def invalidate(self) -> None:
        self._index_cache = None
        self._movers_cache = None
        self._opps_cache = None

    # -- indices ------------------------------------------------------------------

    def _indices(self, now: float) -> dict:
        if self._index_cache is not None and _fresh(self._index_cache_at, INDEX_TTL_SECONDS, now):
            return self._index_cache
        end = date.today()
        start = end - timedelta(days=INDEX_CANDLE_DAYS)
        items: list[dict] = []
        quotes: dict = {}
        try:
            quotes = self._client.fetch_full_quotes([d["key"] for d in INDEX_DEFS])
        except (ProviderError, ProviderUnavailableError) as exc:
            logger.warning("Index quotes unavailable: %s", getattr(exc, "message", type(exc).__name__))

        for definition in INDEX_DEFS:
            key = definition["key"]
            item = {
                "key": key,
                "name": definition["name"],
                "value": None,
                "day_change": None,
                "day_change_pct": None,
                "open": None,
                "high": None,
                "low": None,
                "chart": [] if definition.get("chart") else None,
                "status": DataStatus.UNAVAILABLE.value,
                "source": None,
            }
            # Candles first: they carry the honest day change (last vs previous close).
            try:
                candles = self._client.fetch_daily_candles(key, start, end)
                closes: list[tuple[str, float]] = []
                for candle in candles:
                    if not isinstance(candle, (list, tuple)) or len(candle) < 5:
                        continue
                    day = _candle_date(candle[0])
                    close = _num(candle[4])
                    if day is None or close is None:
                        continue
                    closes.append((day.isoformat(), close))
                if closes:
                    closes.sort(key=lambda c: c[0])
                    last_day, last_close = closes[-1]
                    prev_close = closes[-2][1] if len(closes) >= 2 else None
                    item["value"] = last_close
                    if prev_close:
                        change = last_close - prev_close
                        item["day_change"] = change
                        item["day_change_pct"] = (change / prev_close) * 100.0
                    item["status"] = DataStatus.CACHED.value
                    item["source"] = "upstox"
                    if definition.get("chart"):
                        item["chart"] = [
                            {"date": d, "close": c} for d, c in closes
                        ]
            except (ProviderError, ProviderUnavailableError) as exc:
                logger.warning("Index candles unavailable for %s: %s", key, getattr(exc, "message", type(exc).__name__))
            # Live quote supersedes the candle level (same source, fresher).
            raw = quotes.get(key.replace("|", ":"))
            if isinstance(raw, dict):
                last = _num(raw.get("last_price"))
                ohlc = raw.get("ohlc") if isinstance(raw.get("ohlc"), dict) else {}
                if last is not None:
                    item["value"] = last
                    item["open"] = _num(ohlc.get("open"))
                    item["high"] = _num(ohlc.get("high"))
                    item["low"] = _num(ohlc.get("low"))
                    # Keep the candle-derived day change (quotes carry no
                    # prev_close for indices — verified live).
                    item["status"] = DataStatus.LIVE.value
            items.append(item)
        self._index_cache = {"items": items}
        self._index_cache_at = now
        return self._index_cache

    # -- movers -------------------------------------------------------------------

    def _tracked_instruments(self) -> list[dict]:
        """Tracked companies: static universe + registered dynamic equities,
        with their instrument keys when known."""
        out: list[dict] = []
        seen: set[str] = set()
        keys_by_symbol: dict[str, str] = {}
        try:
            for row in self.instrument_repo.list_all():
                sym = str(row.get("symbol") or "").upper()
                key = str(row.get("instrument_key") or "")
                if sym and key:
                    keys_by_symbol.setdefault(sym, key)
        except Exception:
            pass
        for entry in self._universe_entries():
            sym = entry.symbol.upper()
            if sym in seen:
                continue
            seen.add(sym)
            key = getattr(entry, "instrument_key", None) or keys_by_symbol.get(sym)
            if not key:
                continue  # without a key there is no real quote — never guessed
            out.append({"symbol": sym, "name": entry.name, "instrument_key": key})
        return out

    def _tracked_symbols(self) -> int:
        return len(self._tracked_instruments())

    def _movers(self, now: float) -> dict:
        if self._movers_cache is not None and _fresh(self._movers_cache_at, MOVERS_TTL_SECONDS, now):
            return self._movers_cache
        instruments = self._tracked_instruments()
        quotes: dict = {}
        quote_status = DataStatus.UNAVAILABLE.value
        if instruments:
            try:
                quotes = self._client.fetch_full_quotes(
                    [i["instrument_key"] for i in instruments]
                )
                quote_status = DataStatus.LIVE.value
            except (ProviderError, ProviderUnavailableError) as exc:
                logger.warning(
                    "Mover quotes unavailable: %s", getattr(exc, "message", type(exc).__name__)
                )
                quote_status = DataStatus.ERROR.value
        rows: list[dict] = []
        by_token: dict[str, dict] = {}
        for symbol, key in ((i["symbol"], i["instrument_key"]) for i in instruments):
            by_token[key] = {"symbol": symbol}
        for _quote_key, raw in quotes.items():
            if not isinstance(raw, dict):
                continue
            token = str(raw.get("instrument_token") or "")
            hint = by_token.get(token, {})
            symbol = hint.get("symbol") or str(raw.get("symbol") or "").upper()
            name = symbol
            for i in instruments:
                if i["symbol"] == symbol:
                    name = i["name"]
                    break
            q = normalize_quote(raw, instrument_key=token, fallback_symbol=symbol)
            q["name"] = name
            q["status"] = quote_status
            rows.append(q)
        rows = [r for r in rows if r.get("day_change_pct") is not None and r.get("last_price") is not None]
        rows.sort(key=lambda r: r["day_change_pct"], reverse=True)
        gainers = rows[:MOVER_LIMIT]
        losers = list(reversed(rows[-MOVER_LIMIT:]))
        self._movers_cache = {
            "status": quote_status,
            "tracked": len(instruments),
            "quoted": len(rows),
            "gainers": gainers,
            "losers": losers,
        }
        self._movers_cache_at = now
        return self._movers_cache

    # -- opportunities (stored analyst outputs only) --------------------------------

    def _opportunities(self, now: float) -> dict:
        if self._opps_cache is not None and _fresh(self._opps_cache_at, OPPORTUNITIES_TTL_SECONDS, now):
            return self._opps_cache
        names: dict[str, str] = {}
        try:
            for entry in self._universe_entries():
                names[entry.symbol.upper()] = entry.name
        except Exception:
            pass
        latest_by_symbol: dict[str, dict] = {}
        try:
            rows = self.agent_output_repo.list_outputs(limit=500)
        except Exception as exc:
            logger.warning("Stored outputs read failed: %s", type(exc).__name__)
            rows = []
        company_analysts = {"firm_analyst", "industry_analyst", "sentiment_analyst"}
        for row in rows:
            if row.get("agent_id") not in company_analysts:
                continue
            entity = str(row.get("entity_id") or "").upper()
            if not entity or row.get("score") is None:
                continue
            prev = latest_by_symbol.get(entity)
            if prev is None or str(row.get("generated_at")) > str(prev.get("generated_at")):
                latest_by_symbol[entity] = row
        ranked = sorted(
            latest_by_symbol.values(),
            key=lambda r: float(r.get("score") or 0.0),
            reverse=True,
        )
        items = [
            {
                "symbol": r.get("entity_id"),
                "name": names.get(str(r.get("entity_id")).upper(), r.get("entity_id")),
                "agent_id": r.get("agent_id"),
                "score": r.get("score"),
                "signal": r.get("signal"),
                "confidence": r.get("confidence"),
                "status": r.get("status"),
                "generated_at": str(r.get("generated_at")),
                "rationale": (r.get("rationale") or "")[:160],
            }
            for r in ranked[:MOVER_LIMIT]
        ]
        self._opps_cache = {
            "status": DataStatus.CACHED.value if items else DataStatus.UNAVAILABLE.value,
            "count": len(items),
            "items": items,
        }
        self._opps_cache_at = now
        return self._opps_cache


def _utcnow_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()
