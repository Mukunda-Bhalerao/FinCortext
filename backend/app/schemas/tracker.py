from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.insights import Fact, Narrative
from app.schemas.portfolio import CurvePoint

Period = Literal["last_visit", "today", "1w", "1m", "start"]


class PortfolioIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    kind: Literal["paper", "tracking"] = "tracking"
    starting_cash: float | None = Field(None, ge=10_000, le=1e9)  # paper accounts
    plan: Literal["zero", "flat20"] = "zero"  # brokerage plan for paper accounts


class RenameIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)


class PositionIn(BaseModel):
    symbol: str = Field(min_length=1, max_length=40)
    quantity: float | None = Field(None, gt=0, le=1e8)
    amount: float | None = Field(None, gt=0, le=1e11)  # rupees to invest; whole shares bought
    entry_date: date | None = None  # bought earlier: that session's close unless a price is given
    entry_price: float | None = Field(None, gt=0, le=1e7)


class QuantityIn(BaseModel):
    quantity: float = Field(gt=0, le=1e8)


class Position(BaseModel):
    id: str
    symbol: str
    name: str | None
    instrument_key: str
    sector: str
    quantity: float
    entry_price: float
    entry_at: datetime
    entry_basis: str  # how the entry price was set
    price: float | None
    price_basis: str | None
    value: float | None
    cost: float
    pnl: float | None
    pnl_pct: float | None
    day_change: float | None
    day_change_pct: float | None
    weight: float | None
    charges: float = 0.0  # buy charges paid on this lot (paper accounts)
    reason: str | None = None
    tag: str | None = None
    break_even: float | None = None  # sell price that returns the money put in, after charges


class TrackedPortfolio(BaseModel):
    id: str
    name: str
    created_at: datetime
    last_viewed_at: datetime | None
    positions: list[Position]
    value: float | None
    cost: float
    pnl: float | None
    pnl_pct: float | None
    day_change: float | None
    day_change_pct: float | None
    priced_at: datetime
    kind: Literal["paper", "tracking"] = "tracking"
    plan: str = "zero"
    starting_cash: float | None = None
    cash: float | None = None
    reserved: float = 0.0  # cash set aside for open buy orders
    account_value: float | None = None  # cash plus holdings at current prices
    account_return: float | None = None  # account value against the starting cash
    realized: float = 0.0  # net profit locked in by sells
    charges_paid: float = 0.0


class PortfolioSummaryRow(BaseModel):
    id: str
    name: str
    created_at: datetime
    last_viewed_at: datetime | None
    positions: int
    value: float | None
    cost: float
    pnl: float | None
    pnl_pct: float | None
    day_change_pct: float | None
    kind: Literal["paper", "tracking"] = "tracking"
    cash: float | None = None
    account_value: float | None = None
    account_return: float | None = None


class Move(BaseModel):
    date: date
    change_pct: float
    live: bool = False  # today's move so far, not a completed session


class Headline(BaseModel):
    title: str
    link: str
    publisher: str
    published_at: datetime | None
    tone: Literal["positive", "negative", "neutral"]
    near_move: date | None = None  # within a day of one of the stock's big moves


class Dividend(BaseModel):
    ex_date: date
    amount: float


class ResearchShift(BaseModel):
    before_signal: str | None
    after_signal: str
    before_score: float | None
    after_score: float | None
    summary: str
    since: datetime | None


class StockReview(BaseModel):
    symbol: str
    name: str | None
    sector: str
    quantity: float
    start_price: float
    start_basis: str  # "close on 3 Nov" or "your entry on 5 Nov"
    end_price: float
    return_pct: float
    contribution: float  # rupees
    contribution_share: float  # of the absolute total of contributions, for the bar
    market_return: float | None
    sector_label: str | None
    sector_return: float | None
    stock_specific: float | None  # return beyond its sector (or the market when no sector index)
    driver: Literal["market", "sector", "stock", "mixed"]
    moves: list[Move]
    headlines: list[Headline]
    dividends: list[Dividend]
    research: ResearchShift | None
    events: list[str]
    explanation: str


class Review(BaseModel):
    portfolio_id: str
    period: Period
    period_label: str
    start: datetime
    start_basis: str
    end: datetime
    start_value: float
    end_value: float
    change: float
    change_pct: float | None
    benchmark_label: str
    benchmark_return: float | None
    market_part: float | None  # rupees the NIFTY 50 move alone would explain
    selection_part: float | None
    headline: str
    points: list[str]
    stocks: list[StockReview]
    value_series: list[CurvePoint]
    cost_series: list[CurvePoint]
    facts: list[Fact]
    narrative: Narrative | None = None
    gaps: list[str]
    computed_at: datetime
