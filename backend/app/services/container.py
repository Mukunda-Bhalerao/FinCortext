"""Service container — dependency wiring for the FastAPI application.

Builds providers, storage, repositories, and services once per process.
Tests construct their own containers with fakes/tmp paths.
"""

from __future__ import annotations

from functools import lru_cache

from app.data.providers.market.yfinance_provider import YFinanceMarketProvider
from app.data.storage.duckdb_storage import DuckDBStorage
from app.data.universe.universe_config import get_universe
from app.repositories.agent_output_repository import AgentOutputRepository
from app.repositories.financial_repository import FinancialRepository
from app.repositories.market_repository import MarketRepository
from app.repositories.news_repository import NewsRepository
from app.repositories.provenance_repository import ProvenanceRepository
from app.repositories.universe_repository import UniverseRepository
from app.services.agent_service import AgentService
from app.services.filing_service import FilingService
from app.services.market_service import MarketService


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

        # Providers (replaceable adapters)
        symbol_to_ticker = {e.symbol: e.ticker for e in get_universe()}
        self.market_provider = YFinanceMarketProvider(symbol_to_ticker)

        # Services
        self.market_service = MarketService(
            self.market_provider, self.market_repo, self.provenance_repo
        )
        self.filing_service = FilingService(self.financial_repo, self.provenance_repo)
        self.agent_service = AgentService(
            self.financial_repo, self.market_repo, self.agent_output_repo
        )

        # Keep the universe DB mirror in sync (idempotent).
        try:
            self.universe_repo.sync_from_config()
        except Exception as exc:  # storage problems must not crash startup
            from app.core.logging import get_logger

            get_logger("container").error("Universe sync failed: %s", exc)


@lru_cache(maxsize=1)
def get_container() -> Container:
    return Container()