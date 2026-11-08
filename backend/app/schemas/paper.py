from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

Side = Literal["BUY", "SELL"]
OrderKind = Literal["MARKET", "LIMIT", "SL"]
Validity = Literal["DAY", "GTC"]
OrderStatus = Literal["OPEN", "FILLED", "CANCELLED", "EXPIRED", "REJECTED"]
TAGS = (
    "Results",
    "News",
    "Research signal",
    "Chart pattern",
    "Value",
    "Momentum",
    "Dip buy",
    "Long term",
    "Tip",
    "Experiment",
    "Strategy",
)


class OrderIn(BaseModel):
    symbol: str = Field(min_length=1, max_length=40)
    side: Side
    kind: OrderKind = "MARKET"
    validity: Validity = "DAY"
    quantity: int | None = Field(None, ge=1, le=10_000_000)
    amount: float | None = Field(None, gt=0, le=1e10)  # buy: rupees to spend, whole shares
    limit_price: float | None = Field(None, gt=0)
    trigger_price: float | None = Field(None, gt=0)
    reason: str | None = Field(None, max_length=500)
    tag: str | None = Field(None, max_length=40)
    target_price: float | None = Field(None, gt=0)  # buy only: sell when the price reaches it
    stop_price: float | None = Field(None, gt=0)  # buy only: sell if the price falls to it

    @model_validator(mode="after")
    def _check(self) -> "OrderIn":
        if self.kind == "LIMIT" and self.limit_price is None:
            raise ValueError("A limit order needs a limit price.")
        if self.kind == "SL" and self.trigger_price is None:
            raise ValueError("A stop-loss order needs a trigger price.")
        if self.quantity is None and self.amount is None:
            raise ValueError("Give a quantity or an amount.")
        if self.side == "SELL" and (self.target_price or self.stop_price):
            raise ValueError("Targets and stops attach to buy orders.")
        return self


class ChargesOut(BaseModel):
    brokerage: float
    stt: float
    exchange: float
    sebi: float
    stamp: float
    gst: float
    dp: float
    total: float


class OrderPreview(BaseModel):
    symbol: str
    side: Side
    quantity: int
    price: float
    price_basis: str
    value: float
    charges: ChargesOut
    total: float  # buy: cash needed; sell: cash received
    break_even: float | None  # buy: sell price needed to make zero after all charges
    cash_after: float
    market_open: bool
    fills: str  # when and at what price this order would fill
    warnings: list[str]


class PaperOrder(BaseModel):
    id: str
    symbol: str
    instrument_key: str
    side: Side
    kind: OrderKind
    validity: Validity
    quantity: float
    limit_price: float | None
    trigger_price: float | None
    status: OrderStatus
    created_at: datetime
    session: date
    fill_price: float | None
    filled_at: datetime | None
    fill_basis: str | None
    charges: ChargesOut | None
    reason: str | None
    tag: str | None
    target_price: float | None
    stop_price: float | None
    parent_id: str | None
    source: str
    message: str | None


class ClosedTrade(BaseModel):
    id: str
    symbol: str
    quantity: float
    buy_price: float
    buy_at: datetime
    sell_price: float
    sell_at: datetime
    charges: float
    gross: float
    net: float
    return_pct: float  # net of charges, on the money put in
    holding_days: int
    term: Literal["short", "long"]
    buy_reason: str | None
    buy_tag: str | None
    sell_reason: str | None
    index_return: float | None  # NIFTY 50 over the same dates
    beat_index: bool | None
    source: str | None


class JournalEntry(BaseModel):
    """One decision and what came of it."""

    kind: Literal["open", "closed"]
    symbol: str
    at: datetime
    quantity: float
    price: float
    reason: str | None
    tag: str | None
    outcome_pct: float | None
    outcome: float | None  # rupees, net of charges for closed trades
    index_return: float | None
    verdict: str  # plain-language summary of reason vs outcome
    source: str | None


class TagStat(BaseModel):
    tag: str
    trades: int
    wins: int
    net: float
    average_return: float


class TaxYear(BaseModel):
    year: str  # "FY 2026-27"
    short_term_gain: float
    long_term_gain: float
    estimated_tax: float
    note: str


class Scorecard(BaseModel):
    closed_trades: int
    open_positions: int
    wins: int
    losses: int
    win_rate: float | None
    average_win: float | None
    average_loss: float | None
    best: ClosedTrade | None
    worst: ClosedTrade | None
    profit_factor: float | None
    realized_net: float
    charges_paid: float
    charges_share_of_gross: float | None
    days_held_winners: float | None
    days_held_losers: float | None
    beat_index: int
    compared: int
    index_equivalent: float | None  # what the same money in the NIFTY 50 made, closed trades
    by_tag: list[TagStat]
    tax: list[TaxYear]
    lessons: list[str]


class AccountActivity(BaseModel):
    orders: list[PaperOrder]
    trades: list[ClosedTrade]
    journal: list[JournalEntry]
    scorecard: Scorecard
