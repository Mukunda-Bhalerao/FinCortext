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
    aliases: list[str] = Field(
        default_factory=list,
        description=(
            "Alternate names/tickers matched by the Sentiment Analyst's "
            "relevance filter (whole-word for single tokens). Deliberately "
            "excludes bare forms that collide with common words (e.g. bare "
            "'Reliance', bare 'LT') — see universe_config for per-company notes."
        ),
    )
    strict_aliases: list[str] = Field(
        default_factory=list,
        description=(
            "Aliases matched case-sensitively (capitalized form only): brand "
            "tokens that double as ordinary lowercase words."
        ),
    )
    instrument_key: str | None = Field(
        default=None,
        description=(
            "Upstox canonical instrument identifier (e.g. 'NSE_EQ|INE002A01018'). "
            "None for static entries until resolved via Upstox search; set for "
            "dynamically registered NSE equities."
        ),
    )