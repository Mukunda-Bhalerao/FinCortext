"""Unit tests for the FirmAgent with in-memory fake repositories."""

from datetime import date, datetime, timedelta

import pytest

from app.agents.firm.firm_agent import FirmAgent
from app.domain.models.agent_output import AgentId, Signal
from app.domain.models.financial import FinancialObservation
from app.domain.models.market import MarketPrice


class FakeFinancialRepo:
    def __init__(self, observations):
        self._obs = observations

    def get_observations(self, entity_id, metric=None, as_of=None, latest_period=True):
        obs = [o for o in self._obs if o.entity_id == entity_id]
        if metric:
            obs = [o for o in obs if o.metric == metric]
        return obs

    def latest_metric_value(self, entity_id, metric, as_of=None):
        obs = self.get_observations(entity_id, metric)
        return obs[-1] if obs else None


class FakeMarketRepo:
    def __init__(self, prices):
        self._prices = prices

    def get_prices(self, symbol, start=None, end=None):
        return self._prices

    def count(self, symbol=None):
        return len(self._prices)

    def latest_trade_date(self, symbol):
        return self._prices[-1].trade_date if self._prices else None


def _obs(metric, value, period_end=date(2024, 3, 31), unit="INR_cr"):
    return FinancialObservation(
        entity_id="RELIANCE",
        metric=metric,
        value=value,
        unit=unit,
        source_name="test filing",
        period_start=period_end - timedelta(days=365),
        period_end=period_end,
    )


def _prices(days=120, base=100.0, daily=0.001):
    prices = []
    d = date(2024, 1, 1)
    price = base
    while len(prices) < days:
        if d.weekday() < 5:
            prices.append(
                MarketPrice(
                    symbol="RELIANCE",
                    provider_ticker="RELIANCE.NS",
                    trade_date=d,
                    open=price,
                    high=price * 1.01,
                    low=price * 0.99,
                    close=price,
                    volume=1000,
                )
            )
            price *= 1 + daily
        d += timedelta(days=1)
    return prices


def test_firm_agent_full_data_scores_and_signals():
    obs = [
        _obs("total_revenue", 1000),
        _obs("net_income", 150),        # 15% margin → 75/100
        _obs("total_debt", 50),
        _obs("total_equity", 500),      # D/E 0.1 → 95/100
        _obs("pe_ratio", 20, unit="ratio"),  # → (40-20)/30 → 66.7/100
    ]
    agent = FirmAgent(FakeFinancialRepo(obs), FakeMarketRepo(_prices()))
    out = agent.analyze("RELIANCE")
    assert out.agent_id == AgentId.FIRM_ANALYST
    assert out.score is not None and 0 <= out.score <= 100
    assert out.signal in {Signal.BUY, Signal.NEUTRAL, Signal.STRONG_BUY}
    assert out.confidence == 0.72  # coverage 0.8 (growth missing, w=0.2) × quality 0.9
    assert out.status == "OK"
    assert len(out.factors) == 6
    assert any(f.available for f in out.factors)
    assert not any("valuation" == f.name and not f.available for f in out.factors)
    # Deterministic
    out2 = agent.analyze("RELIANCE")
    assert out2.score == out.score and out2.confidence == out.confidence


def test_firm_agent_missing_data_reduces_confidence_and_lists_limitations():
    obs = [_obs("total_revenue", 1000), _obs("net_income", 100)]
    agent = FirmAgent(FakeFinancialRepo(obs), FakeMarketRepo([]))
    out = agent.analyze("RELIANCE")
    assert out.score is not None  # profitability still computable
    assert out.confidence < 0.5
    assert any("momentum" in lim for lim in out.data_limitations)
    assert any(f.name == "market_momentum" and not f.available for f in out.factors)


def test_firm_agent_thin_evidence_reports_degraded():
    """A computed score resting on less than half the documented factor
    weight (momentum only, no filings: weight 0.10) is DEGRADED — a 200
    response must not present thin evidence as a successful analysis."""
    agent = FirmAgent(FakeFinancialRepo([]), FakeMarketRepo(_prices()))
    out = agent.analyze("RELIANCE")
    assert out.score is not None  # momentum is computable
    assert out.status == "DEGRADED"
    assert out.confidence < 0.2
    assert any(f.name == "market_momentum" and f.available for f in out.factors)
    assert len([f for f in out.factors if not f.available]) == 5


def test_firm_agent_no_data_returns_unavailable():
    agent = FirmAgent(FakeFinancialRepo([]), FakeMarketRepo([]))
    out = agent.analyze("RELIANCE")
    assert out.score is None
    assert out.signal == Signal.UNAVAILABLE
    assert out.status == "UNAVAILABLE"
    assert out.confidence == 0.0
    assert out.data_limitations


def test_firm_agent_revenue_growth_uses_previous_period():
    obs = [
        _obs("total_revenue", 1100, period_end=date(2024, 3, 31)),
        _obs("total_revenue", 1000, period_end=date(2023, 3, 31)),  # +10% growth
        _obs("net_income", 150),
        _obs("total_debt", 50),
        _obs("total_equity", 500),
    ]
    agent = FirmAgent(FakeFinancialRepo(obs), FakeMarketRepo([]))
    out = agent.analyze("RELIANCE")
    growth_factor = next(f for f in out.factors if f.name == "revenue_growth")
    assert growth_factor.available
    assert growth_factor.value == pytest.approx(0.10, abs=0.001)


def test_firm_agent_negative_growth_scores_low():
    obs = [
        _obs("total_revenue", 900, period_end=date(2024, 3, 31)),
        _obs("total_revenue", 1000, period_end=date(2023, 3, 31)),  # -10%
        _obs("net_income", 150),
        _obs("total_debt", 50),
        _obs("total_equity", 500),
    ]
    agent = FirmAgent(FakeFinancialRepo(obs), FakeMarketRepo([]))
    out = agent.analyze("RELIANCE")
    growth_factor = next(f for f in out.factors if f.name == "revenue_growth")
    assert growth_factor.contribution == 0.0  # clamped at worst bound


def _snapshot_obs(metric, value):
    """Provider snapshot ratio: no statement period (period_end=None)."""
    return FinancialObservation(
        entity_id="RELIANCE",
        metric=metric,
        value=value,
        unit="ratio",
        source_name="yfinance fundamentals (snapshot ratios)",
        period_end=None,
    )


def test_firm_agent_uses_per_metric_latest_including_snapshots():
    """Mixed-vintage data + period-less snapshot ratios: each metric uses its
    own latest observation instead of a single global period filter dropping
    metrics whose latest filing is older (or undated)."""
    obs = [
        _obs("total_revenue", 1100, period_end=date(2024, 3, 31)),
        _obs("total_revenue", 1000, period_end=date(2023, 3, 31)),
        _obs("net_income", 150, period_end=date(2024, 3, 31)),
        # Debt/equity latest filing is a year older — still usable, not dropped.
        _obs("total_debt", 50, period_end=date(2023, 3, 31)),
        _obs("total_equity", 500, period_end=date(2023, 3, 31)),
        _snapshot_obs("pe_ratio", 22.5),
        _snapshot_obs("roe", 0.19),
    ]
    agent = FirmAgent(FakeFinancialRepo(obs), FakeMarketRepo([]))
    out = agent.analyze("RELIANCE")
    by_name = {f.name: f for f in out.factors}
    assert by_name["profitability"].available
    assert by_name["revenue_growth"].available
    assert by_name["financial_health"].available
    assert by_name["return_on_equity"].available
    assert by_name["valuation"].available
    assert by_name["valuation"].value == 22.5
    assert out.status == "OK"