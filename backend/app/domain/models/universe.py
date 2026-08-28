"""Universe entry model."""

from __future__ import annotations

from pydantic import BaseModel, Field


class UniverseEntry(BaseModel):
    """One company in the configurable stock universe.

    Sector/industry classifications are configuration metadata, not logic.
    """

    symbol: str = Field(description="Internal FinCortext symbol, e.g. RELIANCE")
    name: str
    exchange: str = "NSE"
    ticker: str = Field(description="Provider ticker, e.g. RELIANCE.NS")
    sector: str
    industry: str