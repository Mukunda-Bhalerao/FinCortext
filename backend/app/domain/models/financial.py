"""Canonical financial (fundamental) observation models.

A FinancialObservation is ONE metric value for ONE entity over ONE period,
with full provenance and point-in-time metadata. This is the canonical form
produced by filing ingestion (CSV/XBRL/XML/PDF) and used by the Firm Analyst.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum

from pydantic import BaseModel, Field, model_validator

from app.domain.models.base import DataSourceType, Provenance, utcnow


class StatementType(str, Enum):
    INCOME_STATEMENT = "income_statement"
    BALANCE_SHEET = "balance_sheet"
    CASH_FLOW = "cash_flow"
    OTHER = "other"


class ConsolidationBasis(str, Enum):
    STANDALONE = "standalone"
    CONSOLIDATED = "consolidated"
    UNKNOWN = "unknown"


class FinancialObservation(BaseModel):
    """One canonical financial metric value with provenance."""

    entity_id: str = Field(description="Internal symbol, e.g. RELIANCE")
    metric: str = Field(
        description="Canonical metric key, e.g. total_revenue, net_income, total_debt"
    )
    value: float
    unit: str = Field(default="INR", description="Unit of the value, e.g. INR, INR_lakh, ratio, percent")
    currency: str = "INR"
    period_start: date | None = None
    period_end: date | None = None
    statement_type: StatementType = StatementType.OTHER
    consolidation_basis: ConsolidationBasis = ConsolidationBasis.UNKNOWN
    fiscal_year: str | None = None
    source_type: DataSourceType = DataSourceType.OFFICIAL_FILING
    source_name: str
    source_reference: str | None = None
    raw_document_reference: str | None = None
    content_hash: str | None = None
    filing_date: datetime | None = None
    published_at: datetime | None = None
    available_at: datetime | None = Field(
        default=None,
        description="Point-in-time availability; falls back to published_at/filing_date",
    )
    schema_version: str = "1.0"
    ingested_at: datetime = Field(default_factory=utcnow)

    @model_validator(mode="after")
    def _validate_period(self) -> "FinancialObservation":
        if self.period_start and self.period_end and self.period_start > self.period_end:
            raise ValueError("period_start must be <= period_end")
        return self

    @model_validator(mode="after")
    def _resolve_available_at(self) -> "FinancialObservation":
        if self.available_at is None:
            self.available_at = self.published_at or self.filing_date or self.ingested_at
        return self


class FilingDocument(BaseModel):
    """Metadata about an ingested official document (raw layer)."""

    document_id: str = Field(description="Unique id (content hash based)")
    entity_id: str | None = None
    document_type: str = Field(description="csv | xbrl | xml | pdf")
    file_name: str
    file_path: str
    content_hash: str
    source_type: DataSourceType = DataSourceType.OFFICIAL_FILING
    source_name: str
    source_url: str | None = None
    filing_date: datetime | None = None
    published_at: datetime | None = None
    ingested_at: datetime = Field(default_factory=utcnow)
    observation_count: int = 0
    parse_warnings: list[str] = Field(default_factory=list)
    schema_version: str = "1.0"