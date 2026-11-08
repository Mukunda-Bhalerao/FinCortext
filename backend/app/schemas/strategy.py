from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.schemas.portfolio import CurvePoint

ConditionKind = Literal["price_vs_sma", "sma_cross", "rsi", "return", "from_high"]
Op = Literal["above", "below", "crosses_above", "crosses_below"]


class Condition(BaseModel):
    """One test on the daily chart, evaluated at a session's close.

    price_vs_sma: close against its n-day average.
    sma_cross:    n-day average against the m-day average.
    rsi:          n-day RSI against ``value`` (0-100).
    return:       n-day return against ``value`` (a fraction: 0.05 is 5%).
    from_high:    distance below the 52-week high; "below" means fallen at least ``value``
                  (a dip), "above" means within ``value`` of the high.
    """

    kind: ConditionKind
    op: Op
    n: int = Field(50, ge=1, le=250)
    m: int | None = Field(None, ge=2, le=250)
    value: float | None = None

    @model_validator(mode="after")
    def _check(self) -> "Condition":
        if self.kind == "sma_cross" and not self.m:
            raise ValueError("An average crossover needs a second (slower) average.")
        if self.kind in ("rsi", "return", "from_high") and self.value is None:
            raise ValueError(f"A {self.kind} condition needs a value.")
        if self.kind == "from_high" and self.op not in ("above", "below"):
            raise ValueError("Distance from the high is either above or below a level.")
        return self


class Rules(BaseModel):
    entry: list[Condition] = Field(min_length=1, max_length=4)  # all must hold
    exit: list[Condition] = Field(default_factory=list, max_length=4)  # any one exits
    stop_loss: float | None = Field(None, gt=0, lt=0.9)  # fraction below the buy price
    take_profit: float | None = Field(None, gt=0, le=10)
    max_days: int | None = Field(None, ge=1, le=1000)

    @model_validator(mode="after")
    def _exit_needed(self) -> "Rules":
        if not (self.exit or self.stop_loss or self.take_profit or self.max_days):
            raise ValueError("Give at least one way to exit: a condition, stop, target or days.")
        return self


class BacktestIn(BaseModel):
    symbols: list[str] = Field(min_length=1, max_length=10)
    rules: Rules
    years: int = Field(5, ge=1, le=10)
    capital: float = Field(100_000, ge=10_000, le=1e8)
    plan: Literal["zero", "flat20"] = "zero"


class BacktestTrade(BaseModel):
    entry_date: date
    entry_price: float
    exit_date: date
    exit_price: float
    exit_reason: str
    quantity: int
    net: float
    return_pct: float
    days: int


class Segment(BaseModel):
    label: str
    start: date
    end: date
    strategy_return: float
    hold_return: float
    trades: int


class SymbolResult(BaseModel):
    symbol: str
    start: date
    end: date
    final_value: float
    total_return: float
    cagr: float | None
    max_drawdown: float
    trades: list[BacktestTrade]
    win_rate: float | None
    average_win: float | None
    average_loss: float | None
    exposure: float  # share of days holding shares
    charges: float
    hold_return: float  # buying on the first day and holding, after charges
    index_return: float | None  # NIFTY 50 over the same dates
    equity: list[CurvePoint]  # growth of 1 for the strategy
    hold: list[CurvePoint]
    index: list[CurvePoint]
    segments: list[Segment]  # earlier 70% of the period and the later 30%
    verdict: str
    open_trade: bool  # still holding at the end (valued at the last close)


class BacktestResult(BaseModel):
    rules_text: list[str]
    results: list[SymbolResult]
    skipped: list[str]
    summary: str
    assumptions: list[str]
    computed_at: datetime


class StrategyIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    rules: Rules
    symbols: list[str] = Field(min_length=1, max_length=10)


class ForwardIn(BaseModel):
    portfolio_id: str
    per_trade: float = Field(gt=0, le=1e8)


class Strategy(BaseModel):
    id: str
    name: str
    rules: Rules
    rules_text: list[str]
    symbols: list[str]
    created_at: datetime
    portfolio_id: str | None
    portfolio_name: str | None
    per_trade: float | None
    active: bool
    last_run: date | None
    last_note: str | None
