from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, PrivateAttr

from app.schemas.portfolio import CurvePoint, Excluded, PerfStats

ObjectiveKey = Literal["lower_risk", "balanced", "growth", "income"]
Basis = Literal["measured", "estimate", "observed"]


class Preferences(BaseModel):
    objective: ObjectiveKey = "balanced"
    capital: float = Field(1_000_000.0, ge=10_000, le=1e11)
    max_weight: float | None = Field(None, ge=0.05, le=1.0)
    include: list[str] = Field(default_factory=list, max_length=8)  # NSE symbols to try adding
    exclude: list[str] = Field(default_factory=list, max_length=60)  # watchlist symbols to drop
    research_overlay: bool = False  # off by default: unvalidated (see research validation)
    tax_slab: float = Field(0.30, ge=0.0, le=0.43)  # income-tax rate applied to dividends
    # Fixed weights for some stocks (symbol -> fraction); the rest share what is left in the
    # objective's proportions. Used for "what if X were 30%" scenarios.
    custom_weights: dict[str, float] | None = Field(None, max_length=20)


class ObjectiveInfo(BaseModel):
    key: ObjectiveKey
    label: str
    tagline: str
    method: str


class PlanAsset(BaseModel):
    symbol: str
    name: str | None
    instrument_key: str
    sector: str
    role: Literal["holding", "added"]
    weight: float
    risk_share: float
    volatility: float  # trailing year, annualised
    momentum: float | None  # 12-1 month total return, measured
    dividend_yield: float | None  # trailing 12 months, measured
    research_signal: str | None = None
    research_score: float | None = None
    research_confidence: float | None = None
    price: float | None = None
    price_basis: str | None = None


class RiskSummary(BaseModel):
    volatility: float
    benchmark_volatility: float | None
    level: Literal["low", "moderate", "high", "very_high"]
    level_text: str
    diversification_ratio: float
    diversification_score: int  # 0..100, share of the possible volatility reduction achieved
    effective_n: float
    top_risk_symbol: str
    top_risk_share: float
    largest_weight_symbol: str
    largest_weight: float
    sector_weights: dict[str, float]
    avg_correlation: float | None


class YearReturn(BaseModel):
    year: int
    portfolio: float
    benchmark: float | None
    partial: bool


class Uncertainty(BaseModel):
    excess_low: float  # annualised, 5th percentile
    excess_high: float  # 95th percentile
    prob_outperform: float
    method: str


class HalfResult(BaseModel):
    label: str
    start: date
    end: date
    cagr: float | None
    benchmark_cagr: float | None
    max_drawdown: float | None


class PlanBacktest(BaseModel):
    """Measured: walk-forward simulation from cash on historical prices and dividends."""

    start: date
    end: date
    years: float
    limited_by: str | None
    pre_tax: PerfStats
    after_tax: PerfStats | None
    benchmark: PerfStats
    benchmark_label: str
    baseline: PerfStats | None
    baseline_label: str | None
    curve: list[CurvePoint]
    after_tax_curve: list[CurvePoint]
    benchmark_curve: list[CurvePoint]
    baseline_curve: list[CurvePoint]
    costs_per_year: float
    taxes_per_year: float | None
    dividends_per_year: float
    turnover_per_year: float
    rebalances: int
    years_table: list[YearReturn]
    uncertainty: Uncertainty | None
    return_basis: str
    halves: list[HalfResult] = []


class StressResult(BaseModel):
    key: str
    name: str
    kind: Literal["episode", "worst_month"]
    start: date
    end: date
    portfolio: float | None
    portfolio_drawdown: float | None
    benchmark: float | None
    covered: bool
    note: str | None = None


class TradeLine(BaseModel):
    symbol: str
    instrument_key: str
    price: float | None
    current_qty: float
    current_value: float
    current_weight: float
    target_weight: float
    target_value: float
    delta_value: float
    delta_qty: int
    action: Literal["buy", "sell", "hold"]


class TradePlan(BaseModel):
    basis: Literal["holdings", "capital"]
    total_value: float
    lines: list[TradeLine]
    est_costs: float
    cash_left: float
    realised_gain: float | None
    note: str


class Comparison(BaseModel):
    label: str
    volatility: float
    diversification_ratio: float
    cagr: float | None
    max_drawdown: float | None


class PortfolioPlan(BaseModel):
    preferences: Preferences
    objective: ObjectiveInfo
    computed_at: datetime
    as_of: date | None
    assets: list[PlanAsset]
    excluded: list[Excluded]
    risk: RiskSummary | None
    backtest: PlanBacktest | None
    backtest_note: str | None
    stress: list[StressResult]
    trades: TradePlan | None
    current: Comparison | None
    explanation: list[str]
    weight_note: str | None
    assumptions: list[str]
    limitations: list[str]
    duration_ms: int
    # Daily after-tax and benchmark returns behind the backtest, kept for goal projections.
    _daily: list[float] = PrivateAttr(default_factory=list)
    _bench_daily: list[float] = PrivateAttr(default_factory=list)


class GoalRequest(BaseModel):
    preferences: Preferences
    target: float = Field(gt=0, le=1e11)
    years: int = Field(ge=1, le=30)
    initial: float = Field(ge=0, le=1e11)
    monthly: float = Field(0.0, ge=0, le=1e9)


class GoalPoint(BaseModel):
    year: int
    p10: float
    p50: float
    p90: float
    invested: float


class GoalProjection(BaseModel):
    """A hypothesis from resampled history, not a forecast."""

    target: float
    years: int
    initial: float
    monthly: float
    invested: float
    probability: float
    p10: float
    p50: float
    p90: float
    benchmark_probability: float | None
    benchmark_p50: float | None
    path: list[GoalPoint]
    history_from: date | None
    history_to: date | None
    method: str
    caveats: list[str]


class HoldingIn(BaseModel):
    symbol: str = Field(min_length=1, max_length=40)
    quantity: float = Field(ge=0, le=1e9)
    avg_cost: float | None = Field(None, gt=0, le=1e8)


class HoldingOut(BaseModel):
    symbol: str
    instrument_key: str
    name: str | None
    quantity: float
    avg_cost: float | None
    price: float | None
    price_basis: str | None
    value: float | None
    updated_at: datetime
    source: Literal["manual", "upstox"] = "manual"
    invested: float | None = None  # quantity x average cost, when the cost is known
    pnl: float | None = None
    pnl_pct: float | None = None
    day_change_pct: float | None = None
    weight: float | None = None


class BrokerStatus(BaseModel):
    connected: bool
    can_sync: bool | None  # None until a sync has been attempted
    detail: str
    last_sync: datetime | None
    synced_count: int


class PortfolioSummary(BaseModel):
    holdings: list[HoldingOut]
    total_value: float | None
    total_invested: float | None  # holdings with a known cost only
    pnl: float | None
    pnl_pct: float | None
    day_change: float | None
    cost_coverage: float  # share of value whose average cost is known
    priced_at: datetime
    broker: BrokerStatus
    notes: list[str]
