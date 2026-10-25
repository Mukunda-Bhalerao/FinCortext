"""Candle series per UI timeframe: completed sessions (historical) + current session (intraday)."""

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from app.db import Database
from app.errors import AppError
from app.providers.base import MarketDataProvider
from app.schemas.market import Candle, CandleSeries, Timeframe
from app.services.session import SessionClock
from app.tools.candles import merge_candles
from app.tools.market_hours import to_ist


@dataclass(frozen=True)
class Spec:
    unit: str
    interval: int
    lookback_days: int | None  # None = from EARLIEST
    intraday: bool


EARLIEST = date(2000, 1, 1)
# Lookbacks stay inside the documented per-request limits of the V3 historical API:
# minutes 1-15 -> 1 month, hours -> 1 quarter, days -> 1 decade, weeks/months -> unlimited.
SPECS: dict[str, Spec] = {
    "1m": Spec("minutes", 1, 6, True),
    "5m": Spec("minutes", 5, 28, True),
    "15m": Spec("minutes", 15, 28, True),
    "1H": Spec("hours", 1, 88, True),
    "1D": Spec("days", 1, 5 * 365, True),
    "1W": Spec("weeks", 1, 10 * 365, False),
    "1M": Spec("months", 1, None, False),
}

HIST_TTL = timedelta(hours=1)
INTRADAY_TTL_OPEN = timedelta(seconds=20)
INTRADAY_TTL_CLOSED = timedelta(minutes=10)
SOURCE = "upstox.v3.historical-candle"


def _dump(candles: list[Candle]) -> list[dict]:
    return [c.model_dump() for c in candles]


def _load(rows: list[dict]) -> list[Candle]:
    return [Candle(**r) for r in rows]


class CandleService:
    def __init__(self, db: Database, provider: MarketDataProvider, clock: SessionClock):
        self._db = db
        self._provider = provider
        self._clock = clock

    async def series(self, instrument_key: str, timeframe: Timeframe) -> CandleSeries:
        spec = SPECS[timeframe]
        today = to_ist(datetime.now(UTC)).date()
        start = EARLIEST if spec.lookback_days is None else today - timedelta(spec.lookback_days)
        gaps: list[str] = []

        hist, hist_at = await self._cached(
            f"hist:{instrument_key}:{spec.unit}:{spec.interval}:{today}:{start}",
            HIST_TTL,
            lambda: self._provider.get_historical_candles(
                instrument_key, spec.unit, spec.interval, today, start
            ),
        )
        current: list[Candle] = []
        fetched_at = hist_at
        if spec.intraday:
            state, _ = self._clock.state()
            ttl = INTRADAY_TTL_OPEN if state == "open" else INTRADAY_TTL_CLOSED
            try:
                current, cur_at = await self._cached(
                    f"intraday:{instrument_key}:{spec.unit}:{spec.interval}:{today}",
                    ttl,
                    lambda: self._provider.get_intraday_candles(
                        instrument_key, spec.unit, spec.interval
                    ),
                )
                fetched_at = max(fetched_at, cur_at)
            except AppError as exc:
                gaps.append(f"Current-session candles unavailable: {exc.message}")
        candles = merge_candles(hist, current)
        if not candles:
            gaps.append("The provider returned no candles for this instrument and timeframe.")
        return CandleSeries(
            instrument_key=instrument_key,
            timeframe=timeframe,
            unit=spec.unit,
            interval=spec.interval,
            candles=candles,
            includes_current_session=bool(current),
            source=SOURCE,
            fetched_at=fetched_at,
            data_gaps=gaps,
        )

    async def _cached(self, key: str, ttl: timedelta, fetch) -> tuple[list[Candle], datetime]:
        hit = self._db.cache_get(key)
        if hit is not None:
            return _load(hit[0]), hit[1]
        candles = await fetch()
        stamp = self._db.cache_put(key, SOURCE, _dump(candles), ttl)
        return candles, stamp
