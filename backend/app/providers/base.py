"""Provider interfaces. Everything outside ``providers/`` depends only on these types."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Protocol

from app.schemas.market import Candle


@dataclass(frozen=True)
class ProviderQuote:
    instrument_key: str
    symbol: str | None
    ltp: float | None
    prev_close: float | None
    open: float | None
    high: float | None
    low: float | None
    volume: int | None
    avg_price: float | None
    upper_circuit: float | None
    lower_circuit: float | None
    last_trade_time: datetime | None


@dataclass(frozen=True)
class InstrumentRecord:
    instrument_key: str
    segment: str
    exchange: str
    instrument_type: str
    trading_symbol: str
    name: str | None
    short_name: str | None
    isin: str | None
    exchange_token: str | None
    lot_size: int | None
    tick_size: float | None


@dataclass(frozen=True)
class Profile:
    user_id: str | None
    user_name: str | None


class MarketDataProvider(Protocol):
    name: str

    async def fetch_instruments(self) -> list[InstrumentRecord]: ...

    async def get_quotes(self, instrument_keys: list[str]) -> dict[str, ProviderQuote]: ...

    async def get_historical_candles(
        self, instrument_key: str, unit: str, interval: int, to_date: date, from_date: date
    ) -> list[Candle]: ...

    async def get_intraday_candles(
        self, instrument_key: str, unit: str, interval: int
    ) -> list[Candle]: ...

    async def get_profile(self) -> Profile: ...

    async def get_market_status(self, exchange: str) -> str | None: ...


@dataclass(frozen=True)
class OHLCBar:
    interval: str  # provider interval label, e.g. "1d" or "I1"
    open: float
    high: float
    low: float
    close: float
    volume: int
    start_ms: int


@dataclass(frozen=True)
class Tick:
    instrument_key: str
    ltp: float
    prev_close: float | None
    last_trade_ms: int | None
    volume_today: int | None = None
    avg_price: float | None = None
    bars: list[OHLCBar] = field(default_factory=list)
    server_ms: int | None = None  # provider's send time for the frame that carried the tick


@dataclass(frozen=True)
class FeedEvent:
    """One decoded upstream message: ticks and/or exchange segment status."""

    ticks: list[Tick]
    segment_status: dict[str, str]
    server_ms: int | None


class LiveFeed(Protocol):
    """A streaming connection. ``run`` returns or raises when the connection ends."""

    async def run(
        self,
        initial_keys: list[str],
        on_event: Callable[[FeedEvent], Awaitable[None]],
        on_open: Callable[[], Awaitable[None]],
    ) -> None: ...

    async def subscribe(self, keys: list[str]) -> None: ...

    async def unsubscribe(self, keys: list[str]) -> None: ...
