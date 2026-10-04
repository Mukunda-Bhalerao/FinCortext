"""Service container — dependency wiring for the FastAPI application.

Builds providers, storage, repositories, and services once per process.
Tests construct their own containers with fakes/tmp paths.
"""

from __future__ import annotations

from functools import lru_cache

from app.agents.sentiment.model import get_sentiment_model
from app.data.providers.macro.curated_provider import CuratedMacroProvider
from app.data.providers.macro.upstox_gauges import UpstoxGaugeProvider
from app.data.providers.news.newsapi_provider import NewsAPINewsProvider
from app.data.providers.research.gemini_research import GeminiResearchProvider
from app.data.storage.duckdb_storage import DuckDBStorage
from app.data.universe.universe_config import get_universe, register_dynamic_entry
from app.core.config import settings
from app.repositories.agent_output_repository import AgentOutputRepository
from app.repositories.financial_repository import FinancialRepository
from app.repositories.instrument_repository import InstrumentRepository
from app.repositories.macro_repository import MacroRepository
from app.repositories.market_repository import MarketRepository
from app.repositories.news_repository import NewsRepository
from app.repositories.portfolio_repository import PortfolioRepository
from app.repositories.provenance_repository import ProvenanceRepository
from app.repositories.research_repository import ResearchRepository
from app.repositories.universe_repository import UniverseRepository
from app.services.agent_service import AgentService
from app.services.company_preparation_service import CompanyPreparationService
from app.services.filing_service import FilingService
from app.services.fundamentals_service import FundamentalsService
from app.services.macro_service import MacroService
from app.services.market_service import MarketService
from app.services.news_service import NewsService
from app.services.research_service import ResearchService


class Container:
    """Simple composition root. No framework magic."""

    def __init__(self) -> None:
        self.storage = DuckDBStorage()
        self.market_repo = MarketRepository(self.storage)
        self.financial_repo = FinancialRepository(self.storage)
        self.news_repo = NewsRepository(self.storage)
        self.agent_output_repo = AgentOutputRepository(self.storage)
        self.universe_repo = UniverseRepository(self.storage)
        self.provenance_repo = ProvenanceRepository(self.storage)
        self.macro_repo = MacroRepository(self.storage)
        self.portfolio_repo = PortfolioRepository(self.storage)
        self.instrument_repo = InstrumentRepository(self.storage)

        # Providers (replaceable adapters). The news provider reads its key
        # exclusively from configuration; without NEWS_API_KEY it reports
        # itself unconfigured and the news service degrades gracefully.
        # Upstox is the ONLY market provider (quotes + historical candles,
        # verified live); no fallback provider exists — failures degrade
        # honestly to stored snapshots / explicit statuses.
        symbol_to_ticker = {e.symbol: e.ticker for e in get_universe()}
        from app.data.providers.market.upstox_provider import UpstoxMarketProvider

        # Pre-seed known instrument keys from the persisted registry so
        # restarts resolve without re-searching.
        seed_keys: dict[str, str] = {}
        try:
            for row in self.instrument_repo.list_all():
                sym = str(row.get("symbol") or "").upper()
                key = str(row.get("instrument_key") or "")
                if sym and key:
                    seed_keys[sym] = key
        except Exception:
            seed_keys = {}
        try:
            for e in get_universe():
                k = getattr(e, "instrument_key", None)
                if k:
                    seed_keys[e.symbol] = k
        except Exception:
            pass
        self.market_provider = UpstoxMarketProvider(
            settings.upstox_access_token,
            base_url=settings.upstox_base_url,
            timeout_seconds=settings.upstox_timeout_seconds,
            symbol_to_instrument=seed_keys,
        )
        # News: Google News RSS is the free keyless default; NewsAPI stays as
        # an optional secondary merge source (and as primary when selected).
        # NEWS_PROVIDER=google_rss|newsapi (default google_rss).
        from app.data.providers.news.googlenews_rss import GoogleNewsRssProvider

        rss_provider = GoogleNewsRssProvider()
        newsapi_provider = NewsAPINewsProvider(settings.news_api_key)
        if (settings.news_provider or "google_rss").strip().lower() == "newsapi":
            self.news_provider = newsapi_provider
            self.news_secondary_provider = rss_provider
        else:
            self.news_provider = rss_provider
            self.news_secondary_provider = (
                newsapi_provider if newsapi_provider.is_configured else None
            )
        # Provider fundamentals (fallback/enrichment): the Firm Agent reads
        # the shared financial repository generically and never depends on
        # this provider specifically — official filings stay primary. No
        # fundamentals provider is wired after the Upstox consolidation:
        # refreshes report UNAVAILABLE honestly and stored pre-consolidation
        # observations (relabeled legacy_import) remain usable.
        self.fundamentals_provider = None

        # Services
        self.market_service = MarketService(
            self.market_provider,
            self.market_repo,
            self.provenance_repo,
            instrument_repo=self.instrument_repo,
            universe_repo=self.universe_repo,
        )
        self.filing_service = FilingService(self.financial_repo, self.provenance_repo)
        self.fundamentals_service = FundamentalsService(
            self.fundamentals_provider, self.financial_repo, self.provenance_repo
        )
        self.news_service = NewsService(
            self.news_provider,
            self.news_repo,
            self.provenance_repo,
            secondary_provider=self.news_secondary_provider,
        )
        # Gemini web-research/enrichment layer (grounded search, no scraping).
        # Research-only: company classification, peer discovery, news digests.
        # Never a market-data provider; never replaces deterministic finance.
        # Without GEMINI_API_KEY it degrades to UNAVAILABLE and everything
        # else keeps working.
        self.research_repo = ResearchRepository(self.storage)
        self.research_provider = GeminiResearchProvider(
            settings.gemini_api_key,
            model=settings.gemini_model,
            timeout_seconds=settings.gemini_timeout_seconds,
            web_search_enabled=settings.gemini_web_search_enabled,
        )
        self.research_service = ResearchService(
            self.research_provider, self.research_repo, self.provenance_repo
        )
        self.macro_service = MacroService(
            [
                CuratedMacroProvider(),
                UpstoxGaugeProvider(
                    settings.upstox_access_token,
                    base_url=settings.upstox_base_url,
                    timeout_seconds=settings.upstox_timeout_seconds,
                ),
            ],
            self.macro_repo,
            self.provenance_repo,
        )
        # Central SEARCH -> PREPARE -> STORE -> AGENTS flow: one service warms
        # every repository the analysts read (market, fundamentals, news,
        # peers) whenever a company is selected. Agents stay repository-only.
        self.company_preparation_service = CompanyPreparationService(
            market_service=self.market_service,
            fundamentals_service=self.fundamentals_service,
            news_service=self.news_service,
            market_repo=self.market_repo,
            financial_repo=self.financial_repo,
            news_repo=self.news_repo,
            instrument_repo=self.instrument_repo,
            universe_repo=self.universe_repo,
            research_service=self.research_service,
        )
        # Lazy-loading local FinBERT wrapper — never loads at startup.
        self.sentiment_model = get_sentiment_model()
        self.agent_service = AgentService(
            self.financial_repo,
            self.market_repo,
            self.agent_output_repo,
            news_repo=self.news_repo,
            sentiment_model=self.sentiment_model,
            market_service=self.market_service,
            macro_repo=self.macro_repo,
            portfolio_repo=self.portfolio_repo,
        )

        # Keep the universe DB mirror in sync (idempotent).
        try:
            self.universe_repo.sync_from_config()
        except Exception as exc:  # storage problems must not crash startup
            from app.core.logging import get_logger

            get_logger("container").error("Universe sync failed: %s", exc)

        # Hydrate dynamic Upstox entries persisted in earlier sessions so a
        # valid NSE equity selected once stays selectable after restart.
        try:
            for dyn in self.universe_repo.load_dynamic_entries():
                register_dynamic_entry(dyn)
            # Seed the Upstox resolver cache from the instrument registry.
            seed = getattr(self.market_provider, "cache_instrument", None)
            if callable(seed):
                for row in self.instrument_repo.list_all():
                    try:
                        seed(
                            {
                                "instrument_key": row.get("instrument_key"),
                                "symbol": row.get("symbol"),
                                "trading_symbol": row.get("trading_symbol") or row.get("symbol"),
                                "name": row.get("name") or row.get("symbol"),
                                "exchange": row.get("exchange") or "NSE",
                                "segment": row.get("segment") or "EQ",
                            }
                        )
                    except Exception:
                        continue
        except Exception as exc:
            from app.core.logging import get_logger

            get_logger("container").error("Dynamic universe hydration failed: %s", exc)

        # Repair rows historically stored under provider tickers (e.g.
        # 'TCS.NS' in the `symbol` column) so canonical reads by internal
        # symbol see them. Idempotent; a no-op once every row uses the
        # canonical key.
        try:
            from app.core.logging import get_logger

            rekeyed = self.market_repo.normalize_symbol_keys(
                {e.ticker: e.symbol for e in get_universe()}
            )
            if rekeyed:
                get_logger("container").info(
                    "Market key normalization: re-keyed %d price rows from "
                    "provider tickers to internal symbols",
                    rekeyed,
                )
        except Exception as exc:  # storage problems must not crash startup
            from app.core.logging import get_logger

            get_logger("container").error("Market key normalization failed: %s", exc)


@lru_cache(maxsize=1)
def get_container() -> Container:
    return Container()