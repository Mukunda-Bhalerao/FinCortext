"""Portfolio synthesis models — the Central Orchestrator's output contract.

A PortfolioView explains how the four independent analyst perspectives fit
together for ONE company. It contains NO overall score and NO overall signal:
the perspectives are shown, compared, and traced — never blended into a
single investment rating. Scores shown inside belong to the underlying
analysts, each labeled with its owner.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.domain.models.base import utcnow

Direction = Literal["positive", "neutral", "negative", "missing"]


class PerspectiveView(BaseModel):
    """One analyst's view, normalized for comparison."""

    agent_id: str = Field(description="firm_analyst | industry_analyst | sentiment_analyst | macro_analyst")
    label: str
    entity_id: str = Field(description="Company symbol, or MACRO_INDIA for the macro view")
    direction: Direction = Field(
        description="Bullish (+)/neutral/bearish (−) leaning, or missing when unavailable"
    )
    signal_label: str = Field(description="Original signal wording, e.g. BUY or NEUTRAL-environment")
    score: float | None = Field(
        default=None,
        description="The analyst's own score (0–100 company score, macro environment score, or None)",
    )
    confidence: float = Field(default=0.0, ge=0, le=1)
    status: str = Field(description="OK | DEGRADED | UNAVAILABLE | ERROR")
    takeaway: str = Field(description="One-line reading of this perspective")
    limitations: list[str] = Field(default_factory=list)
    generated_at: str | None = None


class AgreementView(BaseModel):
    """How the available perspectives line up — shown, never smoothed over."""

    available_count: int
    total_count: int = 4
    positive_count: int = 0
    neutral_count: int = 0
    negative_count: int = 0
    verdict: str = Field(
        description="unanimous-positive | unanimous-negative | unanimous-neutral | "
        "majority-positive | majority-negative | mixed | insufficient"
    )
    conflicts: list[dict] = Field(
        default_factory=list,
        description="[{between: [label_a, label_b], description}] for opposing pairs",
    )
    summary: str = Field(description="Plain-language agreement statement")


class ScenarioView(BaseModel):
    """One conditional case, grounded in actual inputs — never a prediction."""

    label: str = Field(description="Base case | Bull case | Bear case")
    leaning: str
    conditions: list[str] = Field(
        description="Concrete conditions derived from real factors/limitations"
    )
    note: str = Field(description="What this case assumes, in plain words")


class PortfolioEvidence(BaseModel):
    """Traceability pointer back to one underlying analyst output."""

    agent_id: str
    entity_id: str
    signal: str | None = None
    score: float | None = None
    status: str | None = None
    generated_at: str | None = None
    note: str | None = None


class PortfolioView(BaseModel):
    """Explainable synthesis of the four analyst perspectives for one company."""

    agent_id: str = "portfolio_agent"
    entity_id: str = Field(description="Internal company symbol under review")
    generated_at: datetime = Field(default_factory=utcnow)
    perspectives: list[PerspectiveView] = Field(default_factory=list)
    agreement: AgreementView = Field(default_factory=AgreementView)
    scenarios: list[ScenarioView] = Field(default_factory=list)
    thesis: str = Field(default="", description="Evidence-grounded investment thesis")
    evidence: list[PortfolioEvidence] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    coverage: float = Field(default=0.0, ge=0, le=1)
    confidence: float = Field(default=0.0, ge=0, le=1)
    status: str = Field(
        default="UNAVAILABLE",
        description="OK | DEGRADED | UNAVAILABLE — reflects perspective coverage",
    )
    rationale: str = Field(default="", description="Why the synthesis concludes what it does")
    data_limitations: list[str] = Field(default_factory=list)
    provenance: dict[str, Any] = Field(default_factory=dict)
    methodology: str = "portfolio_agent_v1"
