"""Agent orchestration service — builds agents with repositories and runs them."""

from __future__ import annotations

from app.agents.firm.firm_agent import FirmAgent
from app.agents.industry.industry_agent import IndustryAgent
from app.agents.sentiment.sentiment_agent import SentimentAgent
from app.core.exceptions import NotFoundError
from app.data.universe.universe_config import get_universe_entry
from app.domain.models.agent_output import AgentId, AgentOutput
from app.repositories.agent_output_repository import AgentOutputRepository
from app.repositories.financial_repository import FinancialRepository
from app.repositories.market_repository import MarketRepository
from app.repositories.news_repository import NewsRepository


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
    ):
        self.financial_repo = financial_repo
        self.market_repo = market_repo
        self.output_repo = output_repo
        self._firm_agent = FirmAgent(financial_repo, market_repo, output_repo)
        self._industry_agent = IndustryAgent(market_repo, financial_repo, output_repo)
        # Sentiment requires news storage + an (injectable) sentiment model.
        self._sentiment_agent = (
            SentimentAgent(news_repo, output_repo, sentiment_model)
            if news_repo is not None
            else None
        )

    def run_agent(self, agent_id: str, symbol: str, *, persist: bool = True) -> AgentOutput:
        """Run one implemented agent; unknown agents are rejected explicitly.

        `persist=False` runs analysis without writing to the output history
        (used for deterministic re-runs / previews).
        """
        get_universe_entry(symbol)  # validate symbol
        agent_id = AGENT_ALIASES.get(agent_id.lower(), agent_id.lower())
        if agent_id == AgentId.FIRM_ANALYST.value:
            return self._firm_agent.run(symbol, persist=persist)
        if agent_id == AgentId.INDUSTRY_ANALYST.value:
            return self._industry_agent.run(symbol, persist=persist)
        if agent_id == AgentId.SENTIMENT_ANALYST.value:
            if self._sentiment_agent is None:
                raise NotFoundError(
                    "Sentiment analyst requires news storage, which is not "
                    "wired in this container."
                )
            return self._sentiment_agent.run(symbol, persist=persist)
        if agent_id in {AgentId.MACRO_ANALYST.value, AgentId.PORTFOLIO_AGENT.value}:
            raise NotFoundError(
                f"Agent '{agent_id}' is not implemented yet. "
                "Implemented agents: firm_analyst, industry_analyst, "
                "sentiment_analyst."
            )
        raise NotFoundError(f"Unknown agent '{agent_id}'")

    def list_outputs(self, agent_id: str | None, symbol: str | None, limit: int = 50) -> list[dict]:
        return self.output_repo.list_outputs(agent_id, symbol, limit)