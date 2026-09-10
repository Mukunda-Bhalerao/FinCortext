"""Canonical macro models.

A MacroObservation is ONE indicator reading for ONE period with full
provenance. Unlike company data, macro series are market-wide (India) and
are frequently revised — so the observation period (`period_end`), the
publication/release date (`published_at`), and the ingestion timestamp are
stored separately. Point-in-time consumers must filter on `available_at`
(= `published_at`, falling back to ingestion time), never on `period_end`.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, model_validator

from app.domain.models.base import DataSourceType, utcnow


class MacroDirection(str, Enum):
    UP = "up"
    DOWN = "down"
    FLAT = "flat"
    UNKNOWN = "unknown"


class MacroSignal(str, Enum):
    """Macro-environment signal vocabulary.

    Deliberately NOT the investment Signal enum (strong_buy … strong_sell):
    a POSITIVE macro environment is not a buy recommendation for any stock.
    """

    POSITIVE = "positive"
    NEUTRAL = "neutral"
    NEGATIVE = "negative"
    UNAVAILABLE = "unavailable"


class MacroObservation(BaseModel):
    """One canonical macro indicator reading."""

    observation_id: str | None = Field(
        default=None, description="Deterministic id (set by the repository)"
    )
    indicator_id: str = Field(
        description="Stable indicator key, e.g. repo_rate, cpi_yoy, usd_inr"
    )
    value: float
    unit: str = Field(description="e.g. %, INR per USD, USD/bbl, index points")
    period_start: date | None = None
    period_end: date | None = Field(
        default=None, description="Observation period (None only for as-of snapshots)"
    )
    observed_at: date | None = Field(
        default=None, description="Market observation date for market-derived series"
    )
    published_at: datetime | None = Field(
        default=None,
        description="Official publication/release timestamp when known",
    )
    available_at: datetime | None = Field(
        default=None,
        description="Point-in-time availability; falls back to published_at/ingested_at",
    )
    source_type: DataSourceType = DataSourceType.UNKNOWN
    source_name: str
    source_url: str | None = None
    content_hash: str | None = None
    notes: str | None = None
    schema_version: str = "1.0"
    ingested_at: datetime = Field(default_factory=utcnow)

    @model_validator(mode="after")
    def _resolve_available_at(self) -> "MacroObservation":
        if self.available_at is None:
            self.available_at = self.published_at or self.ingested_at
        return self


class MacroEvidence(BaseModel):
    """One retrieved fact behind a macro factor (fact, not interpretation)."""

    indicator_id: str
    reference: str = Field(description="e.g. repo_rate@2025-12-05 or usd_inr@2026-09-10")
    value: float | None = None
    unit: str | None = None
    period: str | None = None
    source_name: str | None = None
    source_url: str | None = None
    note: str | None = None


class MacroFactorOutput(BaseModel):
    """One of the seven macro areas: measured value, direction, environment signal."""

    name: str = Field(description="growth | inflation | interest_rates | ...")
    label: str
    value: float | None = Field(
        default=None, description="Headline measured value (None when unavailable)"
    )
    unit: str | None = None
    direction: MacroDirection = MacroDirection.UNKNOWN
    signal: MacroSignal = MacroSignal.UNAVAILABLE
    confidence: float = Field(default=0.0, ge=0, le=1)
    available: bool = True
    data_as_of: str | None = Field(
        default=None, description="Latest observation period/date behind this factor"
    )
    detail: str | None = Field(
        default=None, description="Deterministic explanation of the computation"
    )
    evidence: list[MacroEvidence] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class MacroOutput(BaseModel):
    """Market-wide macro environment view. NOT a company score.

    Entity is always MACRO_INDIA; `requested_symbol` records which company
    context (if any) the run was requested from. The same output applies to
    every company — it must never be presented as a stock recommendation.

    `score` is the 0–100 Macro Environment Score: a linear rescaling of the
    available-factor vote (50 + 50 × net/n), so it always agrees with
    `overall_signal`. Unavailable areas are excluded from it entirely.
    """

    agent_id: str = "macro_analyst"
    entity_id: str = "MACRO_INDIA"
    requested_symbol: str | None = Field(
        default=None, description="Universe symbol context of the request, if any"
    )
    score: float | None = Field(
        default=None,
        ge=0,
        le=100,
        description="Macro Environment Score 0–100 (None when unavailable)",
    )
    overall_signal: MacroSignal = MacroSignal.UNAVAILABLE
    confidence: float = Field(default=0.0, ge=0, le=1)
    status: str = Field(
        default="UNAVAILABLE",
        description="OK | DEGRADED | UNAVAILABLE — reflects data availability",
    )
    factors: list[MacroFactorOutput] = Field(default_factory=list)
    rationale: str = Field(default="")
    data_limitations: list[str] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=utcnow)
    data_through: dict[str, str] = Field(
        default_factory=dict, description="indicator_id → latest observation date used"
    )
    provenance: dict[str, Any] = Field(default_factory=dict)
    methodology: str = "macro_analyst_v1"
