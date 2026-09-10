"""Agent orchestration service — builds agents with repositories and runs them."""

from __future__ import annotations

from app.agents.firm.firm_agent import FirmAgent
from app.agents.industry.industry_agent import IndustryAgent
from app.agents.industry.methodology import MIN_PRICES_FOR_METRICS
from app.agents.macro.macro_agent import MacroAgent
from app.agents.portfolio.portfolio_agent import PortfolioAgent
from app.agents.sentiment.sentiment_agent import SentimentAgent
from app.core.exceptions import NotFoundError
from app.data.universe.universe_config import get_sector_peers, get_universe_entry
from app.domain.models.agent_output import AgentId, AgentOutput
from app.domain.models.macro import MacroOutput
from app.domain.models.portfolio import PortfolioView
from app.repositories.agent_output_repository import AgentOutputRepository
from app.repositories.financial_repository import FinancialRepository
from app.repositories.macro_repository import MacroRepository
from app.repositories.market_repository import MarketRepository
from app.repositories.news_repository import NewsRepository
from app.repositories.portfolio_repository import PortfolioRepository


# URL-friendly aliases → canonical AgentId values.
AGENT_ALIASES = {
    "firm": AgentId.FIRM_ANALYST.value,
    "firm_analyst": AgentId.FIRM_ANALYST.value,
    "industry": AgentId.INDUSTRY_ANALYST.value,
    "industry_analyst": AgentId.INDUSTRY_ANALYST.value,
    "sentiment": AgentId.SENTIMENT_ANALYST.value,
    "sentiment_analyst": AgentId.SENTIMENT_ANALYST.value,
    "macro": AgentId.MACRO_ANALYST.value,
    "macro_analyst": AgentId.MACRO_ANALYST.value,
    "portfolio": AgentId.PORTFOLIO_AGENT.value,
    "portfolio_agent": AgentId.PORTFOLIO_AGENT.value,
}


class AgentService:
    def __init__(
        self,
        financial_repo: FinancialRepository,
        market_repo: MarketRepository,
        output_repo: AgentOutputRepository,
        news_repo: NewsRepository | None = None,
        sentiment_model=None,
        market_service=None,
        macro_repo: MacroRepository | None = None,
        portfolio_repo: PortfolioRepository | None = None,
    ):
        self.financial_repo = financial_repo
        self.market_repo = market_repo
        self.output_repo = output_repo
        # Optional MarketService for agents that prepare their own market
        # data before analysis (Industry Analyst). When absent, agents run
        # purely on cached data (existing behavior; tests/fakes).
        self.market_service = market_service
        self._firm_agent = FirmAgent(financial_repo, market_repo, output_repo)
        self._industry_agent = IndustryAgent(market_repo, financial_repo, output_repo)
        # Sentiment requires news storage + an (injectable) sentiment model.
        self._sentiment_agent = (
            SentimentAgent(news_repo, output_repo, sentiment_model)
            if news_repo is not None
            else None
        )
        # Macro is market-wide: one shared agent over the macro repository.
        self._macro_agent = MacroAgent(macro_repo) if macro_repo is not None else None
        # Portfolio synthesis is stateless over the four analyst outputs.
        self._portfolio_agent = (
            PortfolioAgent(portfolio_repo) if portfolio_repo is not None else None
        )

    def run_agent(
        self, agent_id: str, symbol: str, *, persist: bool = True
    ) -> AgentOutput | MacroOutput | PortfolioView:
        """Run one implemented agent; unknown agents are rejected explicitly.

        `persist=False` runs analysis without writing to the output history
        (used for deterministic re-runs / previews). The Macro Analyst
        returns a MacroOutput (market-wide environment view, NOT a company
        score); the symbol only provides request context. The Portfolio
        Agent runs all four analysts for the symbol, then synthesizes.
        """
        entry = get_universe_entry(symbol)  # validate symbol
        agent_id = AGENT_ALIASES.get(agent_id.lower(), agent_id.lower())
        if agent_id == AgentId.FIRM_ANALYST.value:
            return self._firm_agent.run(entry.symbol, persist=persist)
        if agent_id == AgentId.INDUSTRY_ANALYST.value:
            # Automatic data preparation: ensure the company and its sector
            # peers have sufficient cached market history (fetch only what is
            # missing/stale, via the normal provider/validation pipeline).
            data_preparation = None
            if self.market_service is not None:
                required = [p.symbol for p in get_sector_peers(entry.symbol)]
                data_preparation = self.market_service.ensure_history(
                    required, min_bars=MIN_PRICES_FOR_METRICS
                )
            return self._industry_agent.run(
                entry.symbol, persist=persist, data_preparation=data_preparation
            )
        if agent_id == AgentId.SENTIMENT_ANALYST.value:
            if self._sentiment_agent is None:
                raise NotFoundError(
                    "Sentiment analyst requires news storage, which is not "
                    "wired in this container."
                )
            return self._sentiment_agent.run(entry.symbol, persist=persist)
        if agent_id == AgentId.MACRO_ANALYST.value:
            if self._macro_agent is None:
                raise NotFoundError(
                    "Macro analyst requires macro storage, which is not "
                    "wired in this container."
                )
            # Market-wide output; the validated symbol is request context only.
            return self._macro_agent.run(entry.symbol, persist=persist)
        if agent_id in {AgentId.PORTFOLIO_AGENT.value}:
            if self._portfolio_agent is None:
                raise NotFoundError(
                    "Portfolio agent requires a portfolio repository, which "
                    "is not wired in this container."
                )
            return self.run_portfolio(entry.symbol, persist=persist)
        raise NotFoundError(f"Unknown agent '{agent_id}'")

    def run_portfolio(self, symbol: str, *, persist: bool = True) -> PortfolioView:
        """Run all four analysts for one company, then synthesize.

        Each analyst persists its own output (same as an individual run), so
        the synthesis and the underlying views stay consistent in history.
        """
        if self._portfolio_agent is None:
            raise NotFoundError(
                "Portfolio agent requires a portfolio repository, which "
                "is not wired in this container."
            )
        entry = get_universe_entry(symbol)  # validate symbol
        firm = self.run_agent(AgentId.FIRM_ANALYST.value, entry.symbol, persist=persist)
        industry = self.run_agent(
            AgentId.INDUSTRY_ANALYST.value, entry.symbol, persist=persist
        )
        sentiment = self.run_agent(
            AgentId.SENTIMENT_ANALYST.value, entry.symbol, persist=persist
        )
        macro = self.run_agent(
            AgentId.MACRO_ANALYST.value, entry.symbol, persist=persist
        )
        assert isinstance(firm, AgentOutput)
        assert isinstance(industry, AgentOutput)
        assert isinstance(sentiment, AgentOutput)
        assert isinstance(macro, MacroOutput)
        return self._portfolio_agent.run(
            entry.symbol,
            persist=persist,
            firm=firm,
            industry=industry,
            sentiment=sentiment,
            macro=macro,
        )

    def list_outputs(self, agent_id: str | None, symbol: str | None, limit: int = 50) -> list[dict]:
        return self.output_repo.list_outputs(agent_id, symbol, limit)