from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.plan import ObjectiveKey

Basis = Literal["measured", "estimate", "observed", "replay"]


class Fact(BaseModel):
    """One checkable statement with its source; the unit the assistant must cite."""

    id: str
    text: str
    source: str
    basis: Basis
    as_of: datetime | None = None


class InsightAction(BaseModel):
    kind: Literal["add", "remove", "objective", "open_stock", "holdings", "research"]
    label: str
    symbol: str | None = None
    objective: ObjectiveKey | None = None


class Insight(BaseModel):
    id: str
    kind: Literal["risk", "opportunity", "change", "performance", "data"]
    severity: Literal["high", "medium", "low"]
    title: str
    body: str
    facts: list[str]
    action: InsightAction | None = None


class Narrative(BaseModel):
    text: str
    cited: list[str]
    model: str


class AIStatus(BaseModel):
    enabled: bool
    model: str | None
    detail: str | None = None


class Brief(BaseModel):
    generated_at: datetime
    analysis_at: datetime | None
    headline: str
    insights: list[Insight]
    facts: list[Fact]
    narrative: Narrative | None
    ai: AIStatus


class Scenario(BaseModel):
    objective: ObjectiveKey | None = None
    include: list[str] = Field(default_factory=list, max_length=8)
    exclude: list[str] = Field(default_factory=list, max_length=20)
    max_weight: float | None = Field(None, ge=0.05, le=1.0)
    label: str | None = None


class Turn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=2000)


class AskRequest(BaseModel):
    question: str = Field(min_length=2, max_length=500)
    history: list[Turn] = Field(default_factory=list, max_length=6)
    symbol: str | None = Field(None, max_length=40)


class AskAnswer(BaseModel):
    answer: str
    cited: list[Fact]
    scenario: Scenario | None
    grounded: bool
    model: str | None
    generated_at: datetime
