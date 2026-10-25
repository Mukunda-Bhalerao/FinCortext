from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel

PortfolioState = Literal["not_started", "queued", "running", "ready", "failed"]


class Holding(BaseModel):
    symbol: str
    name: str | None
    instrument_key: str
    sector: str
    history_days: int
    research_signal: str | None = None
    research_score: float | None = None
    research_confidence: float | None = None


class Excluded(BaseModel):
    symbol: str
    reason: str


class PerfStats(BaseModel):
    cagr: float | None
    volatility: float | None
    sharpe: float | None
    max_drawdown: float | None
    total_return: float | None
    start: date | None
    end: date | None
    days: int


class CurvePoint(BaseModel):
    time: int  # UTC seconds at the session date
    value: float


class BacktestResult(BaseModel):
    """Measured: walk-forward simulation on historical prices, costs deducted."""

    stats: PerfStats
    benchmark: PerfStats
    rebalances: int
    turnover_per_year: float
    cost_drag_per_year: float
    curve: list[CurvePoint]
    benchmark_curve: list[CurvePoint]


class StrategyWeight(BaseModel):
    symbol: str
    weight: float
    risk_contribution: float


class StrategyResult(BaseModel):
    key: str
    label: str
    description: str
    weights: list[StrategyWeight]
    sector_weights: dict[str, float]
    # Estimates from the trailing one-year window (in-sample).
    est_volatility: float
    diversification_ratio: float
    effective_n: float
    trailing: PerfStats
    constraints_met: bool
    constraint_note: str | None = None
    backtest: BacktestResult | None
    backtest_note: str | None = None


class Correlation(BaseModel):
    symbols: list[str]
    matrix: list[list[float]]
    average: float | None


class Validation(BaseModel):
    """Measured on the period before the screening window (out of sample for the screen)."""

    start: date
    end: date
    vol_without: float | None
    vol_with: float | None
    sharpe_without: float | None
    sharpe_with: float | None
    mdd_without: float | None
    mdd_with: float | None


class Candidate(BaseModel):
    symbol: str
    name: str | None
    instrument_key: str
    sector: str
    new_sector: bool
    avg_correlation: float
    volatility: float
    weight_if_added: float
    vol_before: float
    vol_after: float
    dr_before: float
    dr_after: float
    sharpe_before: float | None
    sharpe_after: float | None
    rank_score: float
    validation: Validation | None
    research_signal: str | None = None
    research_score: float | None = None
    explanation: str


class Replacement(BaseModel):
    remove: str
    add: str
    vol_before: float
    vol_after: float
    dr_before: float
    dr_after: float
    remove_research_score: float | None
    add_research_score: float | None
    explanation: str


class PortfolioAnalysis(BaseModel):
    computed_at: datetime
    as_of: date | None
    holdings: list[Holding]
    excluded: list[Excluded]
    strategies: list[StrategyResult]
    reference_strategy: str
    correlation: Correlation | None
    candidates: list[Candidate]
    candidate_universe: str
    candidates_screened: int
    replacements: list[Replacement]
    risk_free_rate: float
    risk_free_source: str
    assumptions: list[str]
    limitations: list[str]
    duration_ms: int
    benchmark_label: str = "NIFTY 50"
    return_basis: str = "Price returns"
    objectives: list["ObjectivePreview"] = []
    selection: "SelectionCheck | None" = None


class PortfolioStatus(BaseModel):
    state: PortfolioState
    error: str | None
    stale: bool
    result: PortfolioAnalysis | None


class ObjectivePreview(BaseModel):
    key: str
    label: str
    tagline: str
    volatility: float | None
    cagr: float | None
    after_tax_cagr: float | None
    max_drawdown: float | None
    top_weight_symbol: str | None
    top_weight: float | None


class SelectionCheck(BaseModel):
    """Measured: your stocks against random same-size portfolios over the same sessions."""

    portfolios: int
    size: int
    universe: str
    start: date
    end: date
    your_cagr: float
    median_cagr: float
    p10_cagr: float
    p90_cagr: float
    percentile: float
    note: str


PortfolioAnalysis.model_rebuild()
PortfolioStatus.model_rebuild()
