"""Canonical news and sentiment models."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field

from app.domain.models.base import DataSourceType, utcnow


class NewsArticle(BaseModel):
    """Canonical news article associated with an entity."""

    article_id: str = Field(description="Stable id (content-hash based where possible)")
    title: str = Field(min_length=1)
    description: str | None = None
    content: str | None = None
    source: str | None = None
    source_url: str | None = None
    published_at: datetime | None = None
    collected_at: datetime = Field(default_factory=utcnow)
    language: str | None = None
    entity_id: str | None = Field(
        default=None, description="Internal symbol the article is associated with"
    )
    content_hash: str | None = None
    source_type: DataSourceType = DataSourceType.NEWS_API
    source_name: str = "newsapi"


class SentimentLabel(str, Enum):
    POSITIVE = "positive"
    NEUTRAL = "neutral"
    NEGATIVE = "negative"


class SentimentResult(BaseModel):
    """Model output for one article/document."""

    article_id: str
    entity_id: str | None = None
    label: SentimentLabel
    positive_probability: float = Field(ge=0, le=1)
    neutral_probability: float = Field(ge=0, le=1)
    negative_probability: float = Field(ge=0, le=1)
    model_id: str
    model_confidence: float = Field(ge=0, le=1, description="Probability of the predicted label")
    scored_at: datetime = Field(default_factory=utcnow)