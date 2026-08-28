"""Provider interfaces — the replaceable data-source contracts.

Every external data source is accessed ONLY through these interfaces.
Adapters (yfinance, NewsAPI, future licensed feeds) implement them and
translate provider payloads into canonical domain models at the boundary.
Agents never see provider payloads.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date

from app.domain.models.market import MarketBarSeries, MarketPrice
from app.domain.models.news import NewsArticle


class MarketDataProvider(ABC):
    """Historical OHLCV market data."""

    name: str = "market_provider"

    @abstractmethod
    def fetch_ohlcv(
        self,
        ticker: str,
        start: date,
        end: date,
    ) -> list[MarketPrice]:
        """Return canonical daily bars for `ticker` in [start, end].

        Implementations must raise ProviderError/ProviderUnavailableError on
        failure — never return fabricated data.
        """
        raise NotImplementedError


class FundamentalDataProvider(ABC):
    """Development/fallback fundamental enrichment.

    NOTE: Ingested official filings are the PRIMARY source of truth for
    fundamentals. This provider is for enrichment/fallback only and the Firm
    Agent must not depend specifically on it.
    """

    name: str = "fundamental_provider"

    @abstractmethod
    def fetch_fundamentals(self, ticker: str) -> dict:
        """Return a provider-specific fundamentals dict (adapter-normalized)."""
        raise NotImplementedError


class NewsProvider(ABC):
    """News article retrieval."""

    name: str = "news_provider"

    @abstractmethod
    def fetch_articles(
        self,
        query: str,
        from_date: str | None = None,
        to_date: str | None = None,
        page_size: int = 50,
    ) -> list[NewsArticle]:
        """Return canonical articles for `query` (YYYY-MM-DD date strings).

        Implementations must raise ProviderError/ProviderUnavailableError on
        failure — never fabricate articles.
        """
        raise NotImplementedError