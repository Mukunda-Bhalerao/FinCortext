"""Provider interfaces — the replaceable data-source contracts.

Every external data source is accessed ONLY through these interfaces.
Adapters (Upstox, NewsAPI, future licensed feeds) implement them and
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


class ResearchProvider(ABC):
    """Web-research / enrichment (company classification, peer discovery).

    Research-only: grounded web lookup for metadata the structured providers
    cannot supply (sector/industry for dynamic equities, peer candidates,
    business context). NEVER a market-data source — no prices, volumes,
    timestamps, or ratios. NEVER a replacement for deterministic financial
    calculations. Every claim must carry source evidence (title/URL/domain/
    retrieval time). Implementations must raise
    ProviderError/ProviderUnavailableError on failure — never fabricate.
    """

    name: str = "research_provider"

    @abstractmethod
    def research_company(self, symbol: str, company_name: str) -> dict:
        """Research a company's classification via grounded web search.

        Returns {"company_name", "sector", "industry",
        "business_description", "confidence" (0..1), "sources": [...]}.
        Sources: [{"title", "url", "domain", "retrieved_at"}].
        """
        raise NotImplementedError

    @abstractmethod
    def suggest_peers(
        self,
        symbol: str,
        company_name: str,
        sector: str,
        industry: str,
        *,
        max_peers: int = 8,
    ) -> dict:
        """Suggest listed peer candidates for a company via web research.

        Returns {"peers": [{"symbol", "name", "reason"}], "sources": [...]}.
        Symbols are CANDIDATES ONLY — the caller must validate each one as a
        real NSE listing through Upstox before use. Never invented.
        """
        raise NotImplementedError

    @abstractmethod
    def research_news(self, symbol: str, company_name: str) -> dict:
        """Web-research digest of recent company developments.

        Returns {"items": [{"title", "summary", "url", "source",
        "published_at"|None}], "sources": [...], "retrieved_at"}.
        Clearly labeled web research — NEVER presented as NewsAPI articles
        and never scored by FinBERT as news.
        """
        raise NotImplementedError


class MacroDataProvider(ABC):
    """Macro indicator retrieval (market-wide, not per-company)."""

    name: str = "macro_provider"

    @abstractmethod
    def fetch_indicator(self, indicator_id: str) -> dict:
        """Return a normalized indicator bundle.

        Shape: {"indicator_id", "unit", "source_name",
                "points": [{"period_start"|None, "period_end"|None,
                            "value", "published_at"|None, "source_url"|None,
                            "notes"|None}, ...],
                "warnings": [...]}.
        Dates as ISO strings or date/datetime objects; values numeric.
        Implementations must raise ProviderError/ProviderUnavailableError on
        failure — never fabricate observations.
        """
        raise NotImplementedError