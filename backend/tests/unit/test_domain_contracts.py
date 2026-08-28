"""Unit tests for canonical domain models and the AgentOutput contract."""

from datetime import date, datetime

import pytest

from app.domain.models.agent_output import AgentEvidence, AgentFactor, AgentId, AgentOutput, Signal, signal_from_score
from app.domain.models.base import DataSourceType, Provenance
from app.domain.models.financial import ConsolidationBasis, FinancialObservation, StatementType
from app.domain.models.market import MarketPrice, validate_price_consistency
from app.domain.models.news import NewsArticle, SentimentLabel, SentimentResult


# --- MarketPrice -----------------------------------------------------------


def test_market_price_rejects_negative_price():
    with pytest.raises(Exception):
        MarketPrice(
            symbol="RELIANCE",
            provider_ticker="RELIANCE.NS",
            trade_date=date(2024, 1, 1),
            open=-1,
            high=10,
            low=9,
            close=9.5,
            volume=1000,
        )


def test_validate_price_consistency_flags_bad_ranges():
    bar = MarketPrice(
        symbol="X",
        provider_ticker="X.NS",
        trade_date=date(2024, 1, 1),
        open=11,
        high=8,   # deliberately below low → invalid
        low=9,
        close=12,  # above high → invalid
        volume=1,
    )
    problems = validate_price_consistency(bar)
    assert "high < low" in problems
    assert "close outside high/low range" in problems
    assert "open outside high/low range" in problems


# --- FinancialObservation ---------------------------------------------------


def test_financial_observation_period_ordering_enforced():
    with pytest.raises(Exception):
        FinancialObservation(
            entity_id="RELIANCE",
            metric="total_revenue",
            value=100.0,
            source_name="test",
            period_start=date(2024, 12, 31),
            period_end=date(2024, 1, 1),
        )


def test_financial_observation_available_at_falls_back():
    obs = FinancialObservation(
        entity_id="RELIANCE",
        metric="total_revenue",
        value=100.0,
        source_name="test",
        filing_date=datetime(2024, 5, 1),
    )
    assert obs.available_at == datetime(2024, 5, 1)


def test_financial_observation_point_in_time_explicit():
    obs = FinancialObservation(
        entity_id="RELIANCE",
        metric="total_revenue",
        value=100.0,
        source_name="test",
        period_end=date(2024, 3, 31),
        available_at=datetime(2024, 6, 20),
    )
    # Period end (fiscal) must be distinguishable from availability (public).
    assert obs.period_end == date(2024, 3, 31)
    assert obs.available_at == datetime(2024, 6, 20)


# --- AgentOutput ------------------------------------------------------------


def test_agent_output_contract_roundtrip():
    out = AgentOutput(
        agent_id=AgentId.FIRM_ANALYST,
        entity_id="RELIANCE",
        score=62.5,
        signal=Signal.BUY,
        confidence=0.7,
        factors=[AgentFactor(name="profitability", description="d", value=1.2, contribution=10.0, weight=0.3)],
        rationale="test rationale",
        evidence=[AgentEvidence(data_type="financial_observation", reference="obs-1")],
        data_limitations=["missing metric: roe"],
    )
    d = out.to_storage_dict()
    assert d["agent_id"] == "firm_analyst"
    assert d["score"] == 62.5
    assert "factors_json" in d


def test_signal_from_score_mapping():
    assert signal_from_score(80) == Signal.STRONG_BUY
    assert signal_from_score(70) == Signal.STRONG_BUY
    assert signal_from_score(60) == Signal.BUY
    assert signal_from_score(50) == Signal.NEUTRAL
    assert signal_from_score(40) == Signal.SELL
    assert signal_from_score(20) == Signal.STRONG_SELL


def test_agent_output_score_bounds_enforced():
    with pytest.raises(Exception):
        AgentOutput(agent_id=AgentId.FIRM_ANALYST, entity_id="X", score=150)


# --- News / Sentiment ---------------------------------------------------------


def test_news_article_requires_title():
    with pytest.raises(Exception):
        NewsArticle(article_id="a1", title="")


def test_sentiment_result_probability_bounds():
    with pytest.raises(Exception):
        SentimentResult(
            article_id="a1",
            label=SentimentLabel.POSITIVE,
            positive_probability=1.5,
            neutral_probability=0.0,
            negative_probability=0.0,
            model_id="test-model",
            model_confidence=0.9,
        )


# --- Provenance -----------------------------------------------------------------


def test_provenance_defaults():
    p = Provenance(source_type=DataSourceType.OFFICIAL_FILING, source_name="Annual Report")
    assert p.schema_version == "1.0"
    assert p.ingested_at is not None
    assert p.available_at is None  # resolved by domain models when used