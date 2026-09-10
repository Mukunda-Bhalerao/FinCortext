"""Standardized AgentOutput contract — the critical architectural seam.

Company-scoped agents (Firm, Industry, Sentiment) emit this exact contract.
The Macro Analyst emits the separate MacroOutput contract instead: its
POSITIVE / NEUTRAL / NEGATIVE environment vocabulary must never be mistaken
for buy/sell stock signals. The future Portfolio Agent will consume
these outputs without any hidden agent-to-agent coupling.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from app.domain.models.base import utcnow


class AgentId(str, Enum):
    FIRM_ANALYST = "firm_analyst"
    INDUSTRY_ANALYST = "industry_analyst"
    SENTIMENT_ANALYST = "sentiment_analyst"
    # Reserved for future implementation — do not emit yet.
    MACRO_ANALYST = "macro_analyst"
    PORTFOLIO_AGENT = "portfolio_agent"


class Signal(str, Enum):
    STRONG_BUY = "strong_buy"
    BUY = "buy"
    NEUTRAL = "neutral"
    SELL = "sell"
    STRONG_SELL = "strong_sell"
    UNAVAILABLE = "unavailable"


class AgentFactor(BaseModel):
    """One named, explainable contribution to the score."""

    name: str
    description: str
    value: float | None = Field(
        default=None, description="Raw factor value (None when data was missing)"
    )
    contribution: float | None = Field(
        default=None, description="Weighted points contributed to the final score"
    )
    weight: float | None = Field(default=None, description="Configured weight used")
    available: bool = Field(
        default=True, description="False when the factor could not be computed"
    )
    detail: str | None = Field(
        default=None, description="Human-readable explanation of the computation"
    )


class AgentEvidence(BaseModel):
    """A reference to the underlying data supporting the output."""

    data_type: str = Field(description="market_price | financial_observation | news_article | ...")
    reference: str = Field(description="Identifier or locator of the evidence")
    source_name: str | None = None
    source_type: str | None = None
    timestamp: datetime | None = None
    note: str | None = None


class AgentOutput(BaseModel):
    """Standardized output contract for every FinCortext agent."""

    agent_id: AgentId
    entity_id: str = Field(description="Internal symbol the analysis is about")

    score: float | None = Field(
        default=None, ge=0, le=100, description="Bounded 0-100 score (None when unavailable)"
    )
    signal: Signal = Signal.UNAVAILABLE
    confidence: float = Field(default=0.0, ge=0, le=1)

    factors: list[AgentFactor] = Field(default_factory=list)
    rationale: str = Field(default="", description="Deterministic, human-readable explanation")
    evidence: list[AgentEvidence] = Field(default_factory=list)
    data_limitations: list[str] = Field(default_factory=list)

    generated_at: datetime = Field(default_factory=utcnow)
    data_version: str = "1.0"
    provenance: dict[str, Any] = Field(
        default_factory=dict,
        description="Source references, content hashes, row counts used",
    )
    status: str = Field(
        default="OK",
        description="OK | DEGRADED | UNAVAILABLE — reflects data/model availability",
    )

    def to_storage_dict(self) -> dict:
        """Flatten for DuckDB persistence."""
        return {
            "agent_id": self.agent_id.value,
            "entity_id": self.entity_id,
            "score": self.score,
            "signal": self.signal.value,
            "confidence": self.confidence,
            "factors_json": self.model_dump_json(exclude_none=True),
            "rationale": self.rationale,
            "generated_at": self.generated_at,
            "data_version": self.data_version,
            "status": self.status,
        }


def signal_from_score(score: float) -> Signal:
    """Documented, deterministic score→signal mapping used by all agents.

    >= 70 strong_buy · >= 55 buy · > 45 neutral · > 30 sell · else strong_sell
    """
    if score >= 70:
        return Signal.STRONG_BUY
    if score >= 55:
        return Signal.BUY
    if score > 45:
        return Signal.NEUTRAL
    if score > 30:
        return Signal.SELL
    return Signal.STRONG_SELL