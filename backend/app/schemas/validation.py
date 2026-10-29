from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel

Verdict = Literal["evidence", "negative", "inconclusive", "insufficient"]


class YearIC(BaseModel):
    year: int
    ic: float
    months: int


class SignalTest(BaseModel):
    """Measured: how a signal's scores lined up with the following month's returns."""

    key: str
    label: str
    agent: str
    kind: Literal["composite", "agent", "factor"]
    inputs: str  # what the replay could use
    months: int
    avg_stocks: float
    first_date: date | None
    last_date: date | None
    mean_ic: float | None
    ic_t: float | None
    ic_low: float | None
    ic_high: float | None
    hit_rate: float | None
    first_half_ic: float | None
    second_half_ic: float | None
    spread_annual: float | None  # top fifth minus universe, after costs
    spread_t: float | None
    by_year: list[YearIC]
    verdict: Verdict
    verdict_text: str


class Untestable(BaseModel):
    agent: str
    component: str
    reason: str


class ForwardTracking(BaseModel):
    """Stored live research (all four agents) against what happened afterwards."""

    snapshots: int
    with_outcomes: int
    months_covered: int
    first_snapshot: datetime | None
    outcomes_from: date | None  # when the earliest snapshot's 21-session outcome is known
    pooled_ic: float | None
    by_agent: dict[str, float | None]
    status: str
    # Weekly snapshots of the replayable agents across the universe, recorded before outcomes.
    recorded_snapshots: int = 0
    scored_snapshots: int = 0
    first_recorded: date | None = None
    recorded: list["ForwardSignal"] = []


class ForwardSignal(BaseModel):
    key: str
    label: str
    snapshots: int
    mean_ic: float | None
    verdict: Verdict


class SignalValidation(BaseModel):
    computed_at: datetime
    universe: str
    stocks: int
    start: date | None
    end: date | None
    horizon_sessions: int
    tests: list[SignalTest]
    untestable: list[Untestable]
    tracking: ForwardTracking
    headline: str
    method: list[str]
    limitations: list[str]
    duration_ms: int


class ValidationStatus(BaseModel):
    state: Literal["not_started", "queued", "running", "ready", "failed"]
    error: str | None
    progress: str | None
    result: SignalValidation | None


ForwardTracking.model_rebuild()
