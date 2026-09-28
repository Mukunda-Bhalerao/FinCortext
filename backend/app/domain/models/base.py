"""Shared enums and metadata models used across the domain."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


def utcnow() -> datetime:
    """Timezone-aware UTC now (used for all ingestion timestamps)."""
    return datetime.now(timezone.utc)


class DataSourceType(str, Enum):
    """Where a piece of data originally came from."""

    YFINANCE = "yfinance"
    UPSTOX = "upstox"
    NEWS_API = "news_api"
    GOOGLE_NEWS_RSS = "google_news_rss"
    OFFICIAL_FILING = "official_filing"
    SAMPLE = "sample"
    UNKNOWN = "unknown"


class DataStatus(str, Enum):
    """Explicit data status surfaced to users. Sample data is NEVER silently
    substituted for live data — the status always travels with the data."""

    LIVE = "LIVE"
    CACHED = "CACHED"
    IMPORTED_OFFICIAL = "IMPORTED_OFFICIAL"
    SAMPLE = "SAMPLE"
    UNAVAILABLE = "UNAVAILABLE"
    ERROR = "ERROR"


class Provenance(BaseModel):
    """Provenance metadata attached to stored observations.

    Point-in-time correctness: `period_start/period_end` describe the financial
    period a value covers, while `published_at`/`available_at` describe when the
    information became publicly available. Future backtests must be able to
    distinguish these.
    """

    source_type: DataSourceType
    source_name: str
    source_url: str | None = None
    source_reference: str | None = Field(
        default=None, description="Provider-specific reference (e.g. filing id, article url)"
    )
    raw_document_reference: str | None = Field(
        default=None, description="Path/identifier of the raw stored document"
    )
    content_hash: str | None = Field(
        default=None, description="SHA-256 hash of raw content for dedup/audit"
    )
    schema_version: str = "1.0"
    ingested_at: datetime = Field(default_factory=utcnow)
    filing_date: datetime | None = None
    published_at: datetime | None = None
    available_at: datetime | None = Field(
        default=None,
        description="When the information became publicly available "
        "(defaults to published_at/filing_date when known)",
    )