from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from app.schemas.market import Instrument, NewsItem

AgentName = Literal["firm", "industry", "macro", "sentiment"]
Signal = Literal["positive", "neutral", "negative", "insufficient_data"]
ResearchState = Literal["not_started", "queued", "running", "ready", "failed"]


class Evidence(BaseModel):
    factor: str
    metric: str
    value: float | str | None
    unit: str | None = None  # "%", "x", "pp", "INR", "count"
    detail: str | None = None  # comparison or derivation, e.g. "peer median 18.2"
    source: str
    as_of: datetime | None = None
    score: float | None = None  # -1..1 when the metric feeds the agent score


class FactorScore(BaseModel):
    name: str
    weight: float
    score: float | None
    note: str | None = None


class AgentOutput(BaseModel):
    agent: AgentName
    subject: str
    signal: Signal
    score: float | None  # -1..1; None when there is not enough data
    confidence: float  # 0..1
    coverage: float  # share of factor weight backed by data
    factors: list[FactorScore]
    evidence: list[Evidence]
    data_gaps: list[str]
    rationale: str | None
    rationale_source: Literal["template", "model"] = "template"
    method: str
    computed_at: datetime


class Composite(BaseModel):
    signal: Signal
    score: float | None
    confidence: float
    agents_used: int
    method: str


class Classification(BaseModel):
    industry: str | None
    industry_source: str | None
    sector_index: str | None
    peers: list[str]
    peer_basis: str | None


class ResearchReport(BaseModel):
    instrument: Instrument
    classification: Classification
    agents: list[AgentOutput]
    composite: Composite
    headlines: list[NewsItem]
    computed_at: datetime
    duration_ms: int


class ResearchItem(BaseModel):
    instrument: Instrument
    state: ResearchState
    error: str | None
    stale: bool
    report: ResearchReport | None


class MacroIndicator(BaseModel):
    key: str
    label: str
    value: float | None
    unit: str
    change: float | None  # over `change_window`
    change_unit: str
    change_window: str
    as_of: datetime | None
    source: str
    stale: bool
    problem: str | None = None


class ResearchOverview(BaseModel):
    items: list[ResearchItem]
    macro: list[MacroIndicator]
    refresh_after_hours: float
