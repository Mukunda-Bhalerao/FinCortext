"""Canonical market data models."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field, field_validator

from app.domain.models.base import DataSourceType, Provenance, utcnow


class MarketPrice(BaseModel):
    """One day of canonical OHLCV data for one symbol."""

    symbol: str = Field(description="Internal FinCortext symbol, e.g. RELIANCE")
    exchange: str = Field(default="NSE")
    provider_ticker: str = Field(description="Provider ticker, e.g. RELIANCE.NS")
    trade_date: date
    open: float
    high: float
    low: float
    close: float
    volume: float = Field(ge=0)
    currency: str = "INR"
    source_type: DataSourceType = DataSourceType.YFINANCE
    source_name: str = "yfinance"
    ingested_at: datetime = Field(default_factory=utcnow)

    @field_validator("open", "high", "low", "close")
    @classmethod
    def _positive_prices(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("prices must be positive")
        return v

    @field_validator("high", "low")
    @classmethod
    def _high_gte_low(cls, v: float, info) -> float:
        # Cross-field check happens in validate_price_consistency; keep simple here.
        return v


def validate_price_consistency(price: MarketPrice) -> list[str]:
    """Return a list of consistency problems (empty list = valid)."""
    problems: list[str] = []
    if price.high < price.low:
        problems.append("high < low")
    if price.close > price.high or price.close < price.low:
        problems.append("close outside high/low range")
    if price.open > price.high or price.open < price.low:
        problems.append("open outside high/low range")
    return problems


class MarketBarSeries(BaseModel):
    """A validated, normalized OHLCV series for one symbol."""

    symbol: str
    provider_ticker: str
    bars: list[MarketPrice] = Field(default_factory=list)
    provenance: Provenance | None = None