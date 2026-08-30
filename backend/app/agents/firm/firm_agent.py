"""Firm Analyst — deterministic fundamental + market-behavior scoring.

Consumes canonical data via repositories (never providers):
- FinancialRepository: ingested official filing observations (primary truth)
- MarketRepository: stored price history for momentum

Emits the standardized AgentOutput. See methodology.py for the documented
scoring formula, weights, thresholds, and confidence rules.
"""

from __future__ import annotations

from datetime import date, timedelta

from app.agents.base.base_agent import BaseAgent
from app.agents.firm.methodology import (
    DE_MAX,
    DE_MIN,
    FactorComputation,
    GROWTH_MAX,
    GROWTH_MIN,
    MOMENTUM_MAX,
    MOMENTUM_MIN,
    NET_MARGIN_MAX,
    NET_MARGIN_MIN,
    PE_MAX,
    PE_MIN,
    ROE_MAX,
    ROE_MIN,
    WEIGHTS,
    combine_factor_scores,
    linear_score,
)
from app.core.logging import get_logger
from app.domain.models.agent_output import (
    AgentEvidence,
    AgentFactor,
    AgentId,
    AgentOutput,
    Signal,
    signal_from_score,
)
from app.domain.models.base import DataSourceType
from app.domain.models.financial import FinancialObservation
from app.repositories.agent_output_repository import AgentOutputRepository
from app.repositories.financial_repository import FinancialRepository
from app.repositories.market_repository import MarketRepository

logger = get_logger("agents.firm")

MOMENTUM_WINDOW_DAYS = 90
PREV_PERIOD_MIN_GAP_DAYS = 300


class FirmAgent(BaseAgent):
    agent_id = AgentId.FIRM_ANALYST

    def __init__(
        self,
        financial_repo: FinancialRepository,
        market_repo: MarketRepository,
        output_repo: AgentOutputRepository | None = None,
    ):
        super().__init__(output_repo)
        self.financial_repo = financial_repo
        self.market_repo = market_repo

    # ------------------------------------------------------------------

    def analyze(self, symbol: str) -> AgentOutput:
        entry_symbol = symbol.upper()
        observations = self.financial_repo.get_observations(entry_symbol)
        by_metric = self._latest_by_metric(observations)

        computations: list[FactorComputation] = [
            self._profitability(by_metric),
            self._revenue_growth(entry_symbol, by_metric),
            self._financial_health(by_metric),
            self._return_on_equity(by_metric),
            self._valuation(by_metric),
            self._market_momentum(entry_symbol),
        ]

        score, confidence = combine_factor_scores(computations)
        limitations = [
            c.detail for c in computations if not c.available
        ]
        if score is None:
            limitations.insert(
                0,
                "No analyzable data available. Ingest official filings and/or "
                "refresh market data, then re-run the analysis.",
            )

        # Honest status: a computed score resting on less than half of the
        # documented factor weights (e.g. momentum only, no filings) is
        # DEGRADED, never presented as a fully-successful analysis.
        available_weight = sum(
            WEIGHTS[c.name] for c in computations if c.available and c.points is not None
        )
        if score is None:
            status = "UNAVAILABLE"
        elif available_weight < 0.5:
            status = "DEGRADED"
        else:
            status = "OK"

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

        evidence = self._build_evidence(entry_symbol, observations, by_metric)
        rationale = self._build_rationale(entry_symbol, score, confidence, computations)

        return AgentOutput(
            agent_id=self.agent_id,
            entity_id=entry_symbol,
            score=score,
            signal=signal_from_score(score) if score is not None else Signal.UNAVAILABLE,
            confidence=confidence,
            factors=factors,
            rationale=rationale,
            evidence=evidence,
            data_limitations=limitations,
            provenance={
                "financial_observation_count": len(observations),
                "metrics_available": sorted(by_metric.keys()),
                "market_rows_used": self.market_repo.count(entry_symbol),
                "methodology": "firm_analyst_v1",
            },
            status=status,
        )

    # -- factor computations -------------------------------------------------

    def _latest_by_metric(self, observations: list[FinancialObservation]) -> dict[str, FinancialObservation]:
        """Latest observation per metric (by period_end)."""
        latest: dict[str, FinancialObservation] = {}
        for obs in observations:
            current = latest.get(obs.metric)
            if current is None or (obs.period_end or date.min) > (current.period_end or date.min):
                latest[obs.metric] = obs
        return latest

    def _profitability(self, by_metric) -> FactorComputation:
        ni = by_metric.get("net_income")
        rev = by_metric.get("total_revenue")
        if ni is None or rev is None or rev.value == 0:
            return FactorComputation(
                "profitability", None, None, False,
                "Missing net_income and/or total_revenue — net margin not computable.",
            )
        margin = ni.value / rev.value
        points = linear_score(margin, NET_MARGIN_MIN, NET_MARGIN_MAX)
        return FactorComputation(
            "profitability", round(margin, 4), points, True,
            f"net_margin = {margin:.2%} (net_income/total_revenue) → {points:.0f}/100",
        )

    def _revenue_growth(self, symbol: str, by_metric) -> FactorComputation:
        current = by_metric.get("total_revenue")
        if current is None or current.period_end is None:
            return FactorComputation(
                "revenue_growth", None, None, False,
                "Missing current total_revenue — growth not computable.",
            )
        # Find previous-period revenue at least 300 days earlier.
        previous = None
        for obs in self.financial_repo.get_observations(
            symbol, metric="total_revenue", latest_period=False
        ):
            if obs.period_end is None or current.period_end is None:
                continue
            gap = (current.period_end - obs.period_end).days
            if PREV_PERIOD_MIN_GAP_DAYS <= gap < 400:
                if previous is None or (obs.period_end or date.min) > (previous.period_end or date.min):
                    previous = obs
        if previous is None or previous.value == 0:
            return FactorComputation(
                "revenue_growth", None, None, False,
                "No previous-period total_revenue found — growth not computable.",
            )
        growth = (current.value - previous.value) / abs(previous.value)
        points = linear_score(growth, GROWTH_MIN, GROWTH_MAX)
        return FactorComputation(
            "revenue_growth", round(growth, 4), points, True,
            f"growth = {growth:.2%} vs period ending {previous.period_end} → {points:.0f}/100",
        )

    def _financial_health(self, by_metric) -> FactorComputation:
        debt = by_metric.get("total_debt")
        equity = by_metric.get("total_equity")
        if debt is None or equity is None or equity.value == 0:
            return FactorComputation(
                "financial_health", None, None, False,
                "Missing total_debt and/or total_equity — D/E not computable.",
            )
        de = debt.value / equity.value
        points = linear_score(de, DE_MAX, DE_MIN)  # lower debt is better
        return FactorComputation(
            "financial_health", round(de, 4), points, True,
            f"debt_to_equity = {de:.2f} → {points:.0f}/100",
        )

    def _return_on_equity(self, by_metric) -> FactorComputation:
        roe_obs = by_metric.get("roe")
        if roe_obs is not None:
            roe = roe_obs.value if roe_obs.unit in {"ratio", "percent"} else roe_obs.value
            points = linear_score(roe, ROE_MIN, ROE_MAX)
            return FactorComputation(
                "return_on_equity", round(roe, 4), points, True,
                f"roe (reported) = {roe:.2%} → {points:.0f}/100",
            )
        ni = by_metric.get("net_income")
        equity = by_metric.get("total_equity")
        if ni is None or equity is None or equity.value == 0:
            return FactorComputation(
                "return_on_equity", None, None, False,
                "Missing roe / net_income / total_equity — ROE not computable.",
            )
        roe = ni.value / equity.value
        points = linear_score(roe, ROE_MIN, ROE_MAX)
        return FactorComputation(
            "return_on_equity", round(roe, 4), points, True,
            f"roe (derived) = {roe:.2%} (net_income/total_equity) → {points:.0f}/100",
        )

    def _valuation(self, by_metric) -> FactorComputation:
        pe = by_metric.get("pe_ratio")
        if pe is None:
            return FactorComputation(
                "valuation", None, None, False,
                "Missing pe_ratio — valuation factor unavailable (not fabricated).",
            )
        points = linear_score(pe.value, PE_MAX, PE_MIN)  # lower P/E is better
        return FactorComputation(
            "valuation", round(pe.value, 2), points, True,
            f"pe_ratio = {pe.value:.1f} → {points:.0f}/100",
        )

    def _market_momentum(self, symbol: str) -> FactorComputation:
        prices = self.market_repo.get_prices(symbol)
        if len(prices) < 2:
            return FactorComputation(
                "market_momentum", None, None, False,
                "Insufficient stored price history — momentum not computable. "
                "Use POST /api/market/refresh to fetch prices.",
            )
        latest = prices[-1]
        cutoff = latest.trade_date - timedelta(days=MOMENTUM_WINDOW_DAYS)
        past = [p for p in prices if p.trade_date <= cutoff]
        base = past[-1] if past else prices[0]
        if base.close == 0:
            return FactorComputation(
                "market_momentum", None, None, False,
                "Invalid base price — momentum not computable.",
            )
        momentum = latest.close / base.close - 1
        points = linear_score(momentum, MOMENTUM_MIN, MOMENTUM_MAX)
        return FactorComputation(
            "market_momentum", round(momentum, 4), points, True,
            f"{MOMENTUM_WINDOW_DAYS}d momentum = {momentum:.2%} "
            f"({base.trade_date} → {latest.trade_date}) → {points:.0f}/100",
        )

    # -- output assembly --------------------------------------------------------

    @staticmethod
    def _factor_description(name: str) -> str:
        descriptions = {
            "profitability": "Net margin (net_income / total_revenue)",
            "revenue_growth": "Year-over-year revenue growth",
            "financial_health": "Leverage via debt-to-equity",
            "return_on_equity": "Return on equity (reported or derived)",
            "valuation": "Price-to-earnings ratio (lower is better)",
            "market_momentum": "90-day price momentum",
        }
        return descriptions.get(name, name)

    def _build_evidence(self, symbol, observations, by_metric) -> list[AgentEvidence]:
        evidence: list[AgentEvidence] = []
        for metric, obs in sorted(by_metric.items()):
            evidence.append(
                AgentEvidence(
                    data_type="financial_observation",
                    reference=f"{symbol}/{metric}/{obs.period_end}",
                    source_name=obs.source_name,
                    source_type=obs.source_type.value
                    if isinstance(obs.source_type, DataSourceType)
                    else str(obs.source_type),
                    timestamp=obs.available_at,
                    note=f"{obs.metric}={obs.value} {obs.unit}",
                )
            )
        latest = self.market_repo.latest_trade_date(symbol)
        if latest:
            evidence.append(
                AgentEvidence(
                    data_type="market_price",
                    reference=f"{symbol}/prices/latest={latest.isoformat()}",
                    source_name="market_repository",
                    source_type="stored",
                    timestamp=None,
                    note="Stored OHLCV history used for momentum",
                )
            )
        return evidence

    @staticmethod
    def _build_rationale(symbol, score, confidence, computations) -> str:
        if score is None:
            return (
                f"Firm analysis for {symbol} is unavailable: no analyzable "
                "financial or market data found. Ingest official filings "
                "(Data → Filing Import) and refresh market data first."
            )
        available = [c for c in computations if c.available]
        top = sorted(available, key=lambda c: c.points or 0, reverse=True)
        top_names = ", ".join(c.name for c in top[:2])
        missing = [c.name for c in computations if not c.available]
        rationale = (
            f"Firm score {score:.0f}/100 (confidence {confidence:.0%}) from "
            f"{len(available)}/6 factors. Strongest: {top_names}. "
        )
        if missing:
            rationale += f"Not computed (missing data): {', '.join(missing)}."
        return rationale