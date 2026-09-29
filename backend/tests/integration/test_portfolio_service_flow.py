"""Integration: AgentService portfolio wiring + end-to-end synthesis.

Covers the production wiring (AgentService must hold a portfolio agent when
a portfolio repo is provided), a full run_portfolio over seeded
market/news/macro data with a fake sentiment model, per-company isolation
(TCS/RELIANCE/INFY), DEGRADED handling, and macro evidence deduplication.
No network, no FinBERT.
"""

from datetime import date, datetime, timedelta, timezone

import pytest

from app.agents.macro.macro_agent import MacroAgent
from app.data.storage.duckdb_storage import DuckDBStorage
from app.domain.models.macro import MacroEvidence, MacroFactorOutput, MacroObservation
from app.domain.models.market import MarketPrice
from app.domain.models.news import NewsArticle
from app.repositories.agent_output_repository import AgentOutputRepository
from app.repositories.financial_repository import FinancialRepository
from app.repositories.macro_repository import MacroRepository
from app.repositories.market_repository import MarketRepository
from app.repositories.news_repository import NewsRepository
from app.repositories.portfolio_repository import PortfolioRepository
from app.services.agent_service import AgentService


class FakeSentimentModel:
    model_id = "fake-finbert"

    def analyze(self, texts):
        return [
            {"label": "positive", "positive": 0.9, "neutral": 0.07,
             "negative": 0.03, "confidence": 0.9}
            for _ in texts
        ]


def _seed_prices(market_repo: MarketRepository, symbol: str, days: int = 100,
                 base: float = 100.0) -> None:
    prices = []
    d = date(2024, 1, 1)
    price = base
    while len(prices) < days:
        if d.weekday() < 5:
            prices.append(MarketPrice(
                symbol=symbol,
                provider_ticker=f"{symbol}.NS",
                trade_date=d,
                open=price, high=price * 1.01, low=price * 0.99,
                close=price, volume=1000.0,
            ))
            price *= 1.002
        d += timedelta(days=1)
    market_repo.upsert_bars(prices)


def _seed_news(news_repo: NewsRepository, symbol: str) -> None:
    now = datetime(2026, 9, 9, 10, 0, tzinfo=timezone.utc)
    title = (
        "Tata Consultancy Services TCS reports strong quarterly profit growth"
        if symbol == "TCS" else
        f"{symbol} reports strong quarterly profit growth with record revenue"
    )
    news_repo.save_articles([NewsArticle(
        article_id=f"{symbol.lower()}-strong-quarter",
        title=title,
        description="Revenue beats estimates; profit surges on strong demand.",
        content="Full content about quarterly earnings and profit growth.",
        source="Fixture Times",
        source_url=f"https://example.com/{symbol.lower()}-q",
        published_at=now,
        language="en",
        entity_id=symbol,
        content_hash="hash-" + symbol,
    )])


def _macro_obs(indicator_id, value, period_end, unit="%", notes=None):
    return MacroObservation(
        indicator_id=indicator_id, value=value, unit=unit,
        period_end=period_end, observed_at=period_end,
        published_at=None, source_type="unknown",
        source_name="test source", notes=notes,
    )


def _seed_macro(macro_repo: MacroRepository) -> None:
    today = date.today()
    for i, v in enumerate([6.9, 8.4, 7.8, 7.8, 7.8]):
        macro_repo.save_observations([
            _macro_obs("gdp_real_yoy", v, today - timedelta(days=32 + 92 * (4 - i)),
                       notes="base_year=2022-23")])
    for i, v in enumerate([3.93, 4.38, 4.45, 4.30]):
        macro_repo.save_observations([
            _macro_obs("cpi_yoy", v, today - timedelta(days=10 + 30 * (3 - i)))])
    macro_repo.save_observations([
        _macro_obs("repo_rate", 5.50, today - timedelta(days=90), notes="stance=Neutral"),
        _macro_obs("repo_rate", 5.25, today - timedelta(days=60), notes="stance=Neutral"),
        _macro_obs("repo_rate", 5.25, today - timedelta(days=10), notes="stance=Neutral"),
    ])
    slopes = {"usd_inr": 0.05, "brent_crude": -0.10, "us10y": -0.05, "india_vix": -0.25}
    for indicator_id in ["usd_inr", "brent_crude", "us10y", "india_vix"]:
        start = today - timedelta(days=75)
        for i in range(70):
            macro_repo.save_observations([
                _macro_obs(indicator_id, 100.0 + i * slopes[indicator_id],
                           start + timedelta(days=i), unit="x")])


@pytest.fixture()
def stack(tmp_path):
    storage = DuckDBStorage(tmp_path / "portfolio_service.duckdb")
    storage.connect()
    financial_repo = FinancialRepository(storage)
    market_repo = MarketRepository(storage)
    output_repo = AgentOutputRepository(storage)
    news_repo = NewsRepository(storage)
    macro_repo = MacroRepository(storage)
    portfolio_repo = PortfolioRepository(storage)
    for symbol, base in [("TCS", 100.0), ("INFY", 200.0), ("RELIANCE", 300.0)]:
        _seed_prices(market_repo, symbol, base=base)
        _seed_news(news_repo, symbol)
    _seed_macro(macro_repo)
    service = AgentService(
        financial_repo, market_repo, output_repo,
        news_repo=news_repo, sentiment_model=FakeSentimentModel(),
        macro_repo=macro_repo, portfolio_repo=portfolio_repo,
    )
    yield service, portfolio_repo, macro_repo
    storage.close()


def test_portfolio_agent_wired_when_repo_provided(stack):
    service, _, _ = stack
    assert service._portfolio_agent is not None


def test_without_portfolio_repo_portfolio_run_rejected(tmp_path):
    storage = DuckDBStorage(tmp_path / "no_portfolio.duckdb")
    storage.connect()
    try:
        service = AgentService(
            FinancialRepository(storage), MarketRepository(storage),
            AgentOutputRepository(storage),
        )
        assert service._portfolio_agent is None
        with pytest.raises(Exception):
            service.run_agent("portfolio", "TCS")
    finally:
        storage.close()


def _run_all_analysts(service, symbol):
    """Compute each analyst from its own run (the only supported path);
    portfolio synthesis below must reuse these stored outputs."""
    service.run_agent("firm_analyst", symbol)
    service.run_agent("industry_analyst", symbol)
    service.run_agent("sentiment_analyst", symbol)
    service.run_agent("macro_analyst", symbol)


def test_run_portfolio_end_to_end_tcs(stack):
    service, portfolio_repo, _ = stack
    _run_all_analysts(service, "TCS")
    view = service.run_portfolio("TCS", persist=True)
    assert view.entity_id == "TCS"
    assert [p.agent_id for p in view.perspectives] == [
        "firm_analyst", "industry_analyst", "sentiment_analyst", "macro_analyst"]
    # Company perspectives carry the company; macro stays market-wide.
    by_id = {p.agent_id: p for p in view.perspectives}
    assert by_id["firm_analyst"].entity_id == "TCS"
    assert by_id["macro_analyst"].entity_id == "MACRO_INDIA"
    # No overall score/signal at the top level — synthesis only.
    top = view.model_dump()
    assert "overall_signal" not in top and "score" not in top and "signal" not in top
    # Persisted per company.
    assert portfolio_repo.latest("TCS") is not None
    assert portfolio_repo.latest("INFY") is None


def test_company_switching_isolated(stack):
    service, _, _ = stack
    for symbol in ("TCS", "INFY", "RELIANCE"):
        _run_all_analysts(service, symbol)
    tcs = service.run_portfolio("TCS", persist=True)
    infy = service.run_portfolio("INFY", persist=True)
    rel = service.run_portfolio("RELIANCE", persist=True)
    assert (tcs.entity_id, infy.entity_id, rel.entity_id) == ("TCS", "INFY", "RELIANCE")
    # Macro is market-wide: identical environment signal/score across companies.
    def macro_of(view):
        return next(p for p in view.perspectives if p.agent_id == "macro_analyst")
    assert macro_of(tcs).signal_label == macro_of(infy).signal_label == macro_of(rel).signal_label
    assert macro_of(tcs).score == macro_of(infy).score == macro_of(rel).score


def test_run_portfolio_does_not_rerun_analysts(stack):
    """Synthesis must reuse stored analyst outputs: running it adds no new
    analyst rows, only the synthesis view itself."""
    service, _, _ = stack
    _run_all_analysts(service, "TCS")
    before = service.list_outputs(None, "TCS", limit=100)
    assert len(before) == 4
    view = service.run_portfolio("TCS", persist=True)
    after = service.list_outputs(None, "TCS", limit=100)
    assert len(after) == len(before)
    assert view.agreement.available_count == 4


def test_run_portfolio_with_nothing_stored_marks_all_missing(stack):
    service, _, _ = stack
    view = service.run_portfolio("INFY", persist=False)
    assert view.status == "UNAVAILABLE"
    assert view.agreement.available_count == 0
    assert all(p.direction == "missing" for p in view.perspectives)


def test_degraded_perspective_flagged_not_hidden(stack):
    service, _, _ = stack
    # Firm runs on momentum only here (no filings) → DEGRADED; synthesis must
    # surface that instead of treating it as fully reliable.
    service.run_agent("firm_analyst", "TCS")
    view = service.run_portfolio("TCS", persist=False)
    firm = next(p for p in view.perspectives if p.agent_id == "firm_analyst")
    assert firm.status == "DEGRADED"
    assert any("Firm Analyst" in r and "DEGRADED" in r for r in view.risks)


def test_macro_score_signal_agree_and_dedup(stack):
    _, _, macro_repo = stack
    out = MacroAgent(macro_repo).run("TCS", persist=False)
    assert out.score is not None and 0.0 <= out.score <= 100.0
    assert out.overall_signal.value == (
        "positive" if out.score > 50 else "negative" if out.score < 50 else "neutral")
    refs = [(e.indicator_id, e.reference) for f in out.factors for e in f.evidence]
    assert len(refs) == len(set(refs))


def test_dedupe_removes_repeated_observation():
    from app.domain.models.macro import MacroDirection, MacroSignal

    def factor(name, refs):
        return MacroFactorOutput(
            name=name, label=name, value=1.0, unit="%",
            direction=MacroDirection.FLAT, signal=MacroSignal.NEUTRAL,
            confidence=0.6, available=True, data_as_of="2026-06-05",
            detail="d",
            evidence=[MacroEvidence(
                indicator_id="repo_rate", reference=r, value=5.25,
                unit="%", period="2026-06-05",
                source_name="RBI", source_url=None, note="n") for r in refs],
            limitations=[],
        )

    first = factor("interest_rates", ["repo_rate@2026-06-05"])
    second = factor("policy", ["repo_rate@2026-06-05", "repo_rate@2026-04-04"])
    removed = MacroAgent._dedupe_evidence([first, second])
    assert removed == 1
    assert [e.reference for e in first.evidence] == ["repo_rate@2026-06-05"]
    assert [e.reference for e in second.evidence] == ["repo_rate@2026-04-04"]
