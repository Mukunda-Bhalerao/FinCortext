from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

# live: streamed tick received recently during market hours
# delayed: obtained by REST polling during market hours
# stale: market open but the latest observation is older than the freshness window
# last_close: market closed; values are from the most recent session
# unavailable: provider returned nothing for this instrument
Freshness = Literal["live", "delayed", "stale", "last_close", "unavailable"]

Timeframe = Literal["1m", "5m", "15m", "1H", "1D", "1W", "1M"]


class Instrument(BaseModel):
    instrument_key: str
    symbol: str
    name: str | None
    exchange: str
    segment: str
    instrument_type: str
    isin: str | None = None


class Quote(BaseModel):
    instrument_key: str
    symbol: str | None = None
    ltp: float | None
    prev_close: float | None
    change: float | None
    change_pct: float | None
    open: float | None = None
    high: float | None = None
    low: float | None = None
    volume: int | None = None
    avg_price: float | None = None
    upper_circuit: float | None = None
    lower_circuit: float | None = None
    last_trade_time: datetime | None = None
    source: str
    fetched_at: datetime
    freshness: Freshness


class LabeledQuote(BaseModel):
    label: str
    instrument: Instrument
    quote: Quote | None


class Candle(BaseModel):
    time: int = Field(description="Candle start, Unix seconds (UTC)")
    open: float
    high: float
    low: float
    close: float
    volume: int
    oi: float | None = None


class CandleSeries(BaseModel):
    instrument_key: str
    timeframe: Timeframe
    unit: str
    interval: int
    candles: list[Candle]
    includes_current_session: bool
    source: str
    fetched_at: datetime
    data_gaps: list[str] = []


class MarketStatus(BaseModel):
    state: Literal["open", "pre_open", "closed"]
    basis: Literal["exchange_feed", "schedule"]
    detail: str
    as_of: datetime


class Movers(BaseModel):
    universe: str
    gainers: list[LabeledQuote]
    losers: list[LabeledQuote]
    most_active: list[LabeledQuote]
    advances: int
    declines: int
    unchanged: int
    constituents_total: int
    quotes_received: int
    source: str
    as_of: datetime | None


class NewsItem(BaseModel):
    title: str
    link: str
    publisher: str
    published_at: datetime | None


class NewsFeed(BaseModel):
    items: list[NewsItem]
    sources_ok: list[str]
    sources_failed: list[str]
    fetched_at: datetime


class StockSummary(BaseModel):
    instrument: Instrument
    quote: Quote | None
    week52_high: float | None
    week52_low: float | None
    week52_basis: str | None
    in_watchlist: bool
    problems: list[str] = []


class AuthStatus(BaseModel):
    oauth_configured: bool
    connected: bool
    token_source: Literal["oauth", "env", "none"]
    user_name: str | None
    expected_expiry: datetime | None
    problem: str | None


class LiveStatus(BaseModel):
    transport: Literal["stream", "poll", "idle"]
    state: Literal["connected", "connecting", "disconnected", "unauthorized", "not_connected"]
    detail: str | None
    subscribed: int
    last_message_at: datetime | None
