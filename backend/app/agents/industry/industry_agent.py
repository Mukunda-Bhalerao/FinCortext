"""Industry Analyst — deterministic peer/sector-relative scoring.

Consumes canonical data via repositories (never providers):
- Universe config: peer grouping by sector/industry
- MarketRepository: peer + company price history (momentum, volatility)
- FinancialRepository: peer + company net margins where filings exist

Distinct from the Firm Agent: measures the ENVIRONMENT (peer momentum,
volatility regime) and the company's RELATIVE position (relative strength,
margin vs peer median) — not absolute company quality.

See methodology.py for documented weights/thresholds.
"""

from __future__ import annotations

from datetime import date, timedelta

from app.agents.base.base_agent import BaseAgent
from app.agents.industry.methodology import (
    FactorComputation,
    MARGIN_REL_MAX,
    MARGIN_REL_MIN,
    MIN_PRICES_FOR_METRICS,
    MOMENTUM_MAX,
    MOMENTUM_MIN,
    MOMENTUM_WINDOW_DAYS,
    REL_STRENGTH_MAX,
    REL_STRENGTH_MIN,
    VOL_RATIO_BEST,
    VOL_RATIO_WORST,
    WEIGHTS,
    annualized_volatility,
    combine_factor_scores,
    linear_score,
    median,
)
from app.core.logging import get_logger
from app.data.universe.universe_config import get_sector_peers, get_universe_entry
from app.domain.models.agent_output import (
    AgentEvidence,
    AgentFactor,
    AgentId,
    AgentOutput,
    Signal,
    signal_from_score,
)
from app.repositories.agent_output_repository import AgentOutputRepository
from app.repositories.financial_repository import FinancialRepository
from app.repositories.market_repository import MarketRepository

logger = get_logger("agents.industry")


class IndustryAgent(BaseAgent):
    agent_id = AgentId.INDUSTRY_ANALYST

    def __init__(
        self,
        market_repo: MarketRepository,
        financial_repo: FinancialRepository,
        output_repo: AgentOutputRepository | None = None,
    ):
        super().__init__(output_repo)
        self.market_repo = market_repo
        self.financial_repo = financial_repo

    # ------------------------------------------------------------------

    def analyze(self, symbol: str) -> AgentOutput:
        entry = get_universe_entry(symbol)
        entity = entry.symbol
        peers = [p for p in get_sector_peers(entity) if p.symbol != entity]

        company_metrics = self._price_metrics(entity)
        peer_momenta: list[float] = []
        peer_vols: list[float] = []
        peer_margins: list[float] = []
        peers_with_prices: list[str] = []

        for peer in peers:
            m = self._price_metrics(peer.symbol)
            if m["momentum"] is not None:
                peer_momenta.append(m["momentum"])
                peers_with_prices.append(peer.symbol)
            if m["volatility"] is not None:
                peer_vols.append(m["volatility"])
            margin = self._net_margin(peer.symbol)
            if margin is not None:
                peer_margins.append(margin)

        computations = [
            self._peer_momentum(peer_momenta, peers_with_prices),
            self._relative_strength(company_metrics["momentum"], peer_momenta),
            self._peer_fundamentals(self._net_margin(entity), peer_margins),
            self._sector_volatility(company_metrics["volatility"], peer_vols),
        ]

        score, confidence = combine_factor_scores(computations)
        limitations = [c.detail for c in computations if not c.available]
        if score is None:
            limitations.insert(
                0,
                "No peer/company price data available. Refresh market data for "
                "the universe, then re-run the analysis.",
            )

        factors = [
            AgentFactor(
                name=c.name,
                description=self._factor_description(c.name),
                value=c.value,
                weight=WEIGHTS[c.name],
                contribution=round(c.points, 1) if c.points is not None else None,
                available=c.available,
                detail=c.detail,
            )
            for c in computations
        ]

        evidence = self._build_evidence(entity, peers_with_prices)
        rationale = self._build_rationale(entry.name, score, confidence, computations, len(peers))

        return AgentOutput(
            agent_id=self.agent_id,
            entity_id=entity,
            score=score,
            signal=signal_from_score(score) if score is not None else Signal.UNAVAILABLE,
            confidence=confidence,
            factors=factors,
            rationale=rationale,
            evidence=evidence,
            data_limitations=limitations,
            provenance={
                "sector": entry.sector,
                "industry": entry.industry,
                "peer_count": len(peers),
                "peers_with_prices": peers_with_prices,
                "methodology": "industry_analyst_v1",
            },
            status="OK" if score is not None else "UNAVAILABLE",
        )

    # -- data helpers ----------------------------------------------------------

    def _price_metrics(self, symbol: str) -> dict:
        """Momentum + volatility for one symbol from stored prices."""
        prices = self.market_repo.get_prices(symbol)
        if len(prices) < MIN_PRICES_FOR_METRICS:
            return {"momentum": None, "volatility": None}
        latest = prices[-1]
        cutoff = latest.trade_date - timedelta(days=MOMENTUM_WINDOW_DAYS)
        past = [p for p in prices if p.trade_date <= cutoff]
        base = past[-1] if past else prices[0]
        momentum = latest.close / base.close - 1 if base.close else None

        returns = []
        for prev, cur in zip(prices, prices[1:]):
            if prev.close:
                returns.append(cur.close / prev.close - 1)
        volatility = annualized_volatility(returns)
        return {"momentum": momentum, "volatility": volatility}

    def _net_margin(self, symbol: str) -> float | None:
        obs = self.financial_repo.get_observations(symbol)
        ni = rev = None
        for o in obs:
            if o.metric == "net_income" and (ni is None or (o.period_end or date.min) > (ni.period_end or date.min)):
                ni = o
            if o.metric == "total_revenue" and (rev is None or (o.period_end or date.min) > (rev.period_end or date.min)):
                rev = o
        if ni is None or rev is None or not rev.value:
            return None
        return ni.value / rev.value

    # -- factors -----------------------------------------------------------------

    def _peer_momentum(self, peer_momenta: list[float], peers_with_prices: list[str]) -> FactorComputation:
        med = median(peer_momenta)
        if med is None:
            return FactorComputation(
                "peer_momentum", None, None, False,
                "No peer price history available — peer momentum not computable. "
                "Refresh market data for the universe.",
            )
        points = linear_score(med, MOMENTUM_MIN, MOMENTUM_MAX)
        return FactorComputation(
            "peer_momentum", round(med, 4), points, True,
            f"peer median {MOMENTUM_WINDOW_DAYS}d momentum = {med:.2%} "
            f"({len(peer_momenta)} peers: {', '.join(peers_with_prices)}) → {points:.0f}/100",
        )

    def _relative_strength(self, company_momentum: float | None, peer_momenta: list[float]) -> FactorComputation:
        med = median(peer_momenta)
        if company_momentum is None or med is None:
            return FactorComputation(
                "relative_strength", None, None, False,
                "Company and/or peer momentum unavailable — relative strength "
                "not computable.",
            )
        rel = company_momentum - med
        points = linear_score(rel, REL_STRENGTH_MIN, REL_STRENGTH_MAX)
        return FactorComputation(
            "relative_strength", round(rel, 4), points, True,
            f"company momentum − peer median = {rel:+.2%} → {points:.0f}/100",
        )

    def _peer_fundamentals(self, company_margin: float | None, peer_margins: list[float]) -> FactorComputation:
        med = median(peer_margins)
        if company_margin is None or med is None:
            return FactorComputation(
                "peer_fundamentals", None, None, False,
                "Company and/or peer net margins unavailable (missing filings) — "
                "peer fundamental comparison not computable.",
            )
        rel = company_margin - med
        points = linear_score(rel, MARGIN_REL_MIN, MARGIN_REL_MAX)
        return FactorComputation(
            "peer_fundamentals", round(rel, 4), points, True,
            f"company net margin − peer median = {rel:+.2%} "
            f"({len(peer_margins)} peers with filings) → {points:.0f}/100",
        )

    def _sector_volatility(self, company_vol: float | None, peer_vols: list[float]) -> FactorComputation:
        med = median(peer_vols)
        if company_vol is None or med is None or med == 0:
            return FactorComputation(
                "sector_volatility", None, None, False,
                "Company and/or peer volatility unavailable — volatility "
                "comparison not computable.",
            )
        ratio = company_vol / med
        points = linear_score(ratio, VOL_RATIO_WORST, VOL_RATIO_BEST)
        return FactorComputation(
            "sector_volatility", round(ratio, 3), points, True,
            f"company/peer volatility ratio = {ratio:.2f} "
            f"(company {company_vol:.0%}, peers {med:.0%} annualized) → {points:.0f}/100",
        )

    # -- output assembly ------------------------------------------------------------

    @staticmethod
    def _factor_description(name: str) -> str:
        descriptions = {
            "peer_momentum": "Median sector-peer 90-day momentum (environment)",
            "relative_strength": "Company momentum vs peer median (relative)",
            "peer_fundamentals": "Company net margin vs peer median",
            "sector_volatility": "Company volatility vs peer median (lower is calmer)",
        }
        return descriptions.get(name, name)

    def _build_evidence(self, entity: str, peers_with_prices: list[str]) -> list[AgentEvidence]:
        evidence = [
            AgentEvidence(
                data_type="universe_config",
                reference=f"sector_peers/{entity}",
                source_name="universe_config",
                source_type="configuration",
                note="Peer grouping from versioned universe metadata",
            )
        ]
        for p in peers_with_prices:
            latest = self.market_repo.latest_trade_date(p)
            evidence.append(
                AgentEvidence(
                    data_type="market_price",
                    reference=f"{p}/prices/latest={latest.isoformat() if latest else '?'}",
                    source_name="market_repository",
                    source_type="stored",
                    note="Peer price history used for momentum/volatility",
                )
            )
        return evidence

    @staticmethod
    def _build_rationale(name, score, confidence, computations, peer_count) -> str:
        if score is None:
            return (
                f"Industry analysis for {name} is unavailable: no peer or "
                "company price data found. Refresh market data first."
            )
        available = [c for c in computations if c.available]
        parts = [f"{c.name} ({c.value:+.2%})" for c in available if c.value is not None]
        return (
            f"Industry score {score:.0f}/100 (confidence {confidence:.0%}) from "
            f"{len(available)}/4 factors across {peer_count} sector peers. "
            f"Measured: {', '.join(parts) if parts else 'n/a'}."
        )