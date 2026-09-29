"""Agent orchestration service — builds agents with repositories and runs them."""

from __future__ import annotations

from app.agents.firm.firm_agent import FirmAgent
from app.agents.industry.industry_agent import IndustryAgent
from app.agents.industry.methodology import MIN_PRICES_FOR_METRICS
from app.agents.macro.macro_agent import MacroAgent
from app.agents.portfolio.portfolio_agent import PortfolioAgent
from app.agents.sentiment.sentiment_agent import SentimentAgent
from app.core.exceptions import NotFoundError
from app.core.logging import get_logger
from app.data.universe.universe_config import get_sector_peers, get_universe_entry
from app.domain.models.agent_output import AgentId, AgentOutput
from app.domain.models.macro import MacroOutput
from app.domain.models.portfolio import PortfolioView

logger = get_logger("services.agent")
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
        self.macro_repo = macro_repo
        self.portfolio_repo = portfolio_repo
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

    def _canonical_symbol(self, symbol: str) -> str:
        """Resolve any searched symbol to its canonical internal symbol.

        Renamed/demerged listings (ZOMATO -> ETERNAL, TATAMOTORS -> TMCV)
        resolve through the market service to whatever selection registered;
        truly unknown symbols still raise NotFoundError (honest 404).
        Resolution only — scoring logic is untouched.
        """
        resolve = getattr(self.market_service, "resolve_symbol", None)
        if callable(resolve):
            try:
                return resolve(symbol)["symbol"]
            except NotFoundError:
                raise
            except Exception:
                pass  # provider hiccup: fall through to the registry lookup
        return get_universe_entry(symbol).symbol

    def run_agent(
        self, agent_id: str, symbol: str, *, persist: bool = True
    ) -> AgentOutput | MacroOutput | PortfolioView:
        """Run one implemented agent; unknown agents are rejected explicitly.

        `persist=False` runs analysis without writing to the output history
        (used for deterministic re-runs / previews). The Macro Analyst
        returns a MacroOutput (market-wide environment view, NOT a company
        score); the symbol only provides request context. The Portfolio
        Agent synthesizes the latest stored analyst outputs without
        re-running any analyst.
        """
        entry = get_universe_entry(self._canonical_symbol(symbol))  # validate symbol
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

    def _latest_agent_output(self, agent_id: str, symbol: str) -> AgentOutput | None:
        """Latest stored output for one analyst + company (None when never run).

        Rows persist the full model dump, so rehydration is lossless. A corrupt
        row is logged and treated as missing — never fabricated, never raised.
        """
        try:
            row = self.output_repo.latest_output(agent_id, symbol)
        except Exception as exc:
            logger.warning("Stored-output read failed for %s/%s: %s", agent_id, symbol, exc)
            return None
        if row is None:
            return None
        try:
            return AgentOutput.model_validate_json(row["factors_json"])
        except Exception as exc:
            logger.warning("Stored-output parse failed for %s/%s: %s", agent_id, symbol, exc)
            return None

    def _latest_macro_output(self) -> MacroOutput | None:
        """Latest stored market-wide macro output (None when never run)."""
        if self.macro_repo is None:
            return None
        try:
            row = self.macro_repo.latest_output()
        except Exception as exc:
            logger.warning("Stored macro-output read failed: %s", exc)
            return None
        if row is None:
            return None
        try:
            return MacroOutput.model_validate_json(row["factors_json"])
        except Exception as exc:
            logger.warning("Stored macro-output parse failed: %s", exc)
            return None

    def run_portfolio(self, symbol: str, *, persist: bool = True) -> PortfolioView:
        """Synthesize the latest stored analyst outputs for one company.

        Analysts are NEVER re-run here: each view must already have been
        computed from its own analyst page ("Run fresh analysis") and stored.
        A never-run analyst becomes a "missing" perspective in the synthesis —
        shown explicitly, never filled in. Only the synthesis view itself is
        computed (and persisted) by this call.
        """
        if self._portfolio_agent is None:
            raise NotFoundError(
                "Portfolio agent requires a portfolio repository, which "
                "is not wired in this container."
            )
        entry = get_universe_entry(self._canonical_symbol(symbol))  # validate symbol
        firm = self._latest_agent_output(AgentId.FIRM_ANALYST.value, entry.symbol)
        industry = self._latest_agent_output(AgentId.INDUSTRY_ANALYST.value, entry.symbol)
        sentiment = self._latest_agent_output(AgentId.SENTIMENT_ANALYST.value, entry.symbol)
        macro = self._latest_macro_output()
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