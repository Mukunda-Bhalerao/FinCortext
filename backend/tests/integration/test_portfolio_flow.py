"""Integration: PortfolioAgent synthesis over controlled analyst outputs.

No network, no models. Covers agreement/conflict detection, scenarios
grounded in real inputs, missing-input handling, macro reuse across
companies, determinism, persistence, and the HTTP contract.
"""

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.agents.portfolio.portfolio_agent import PortfolioAgent
from app.data.storage.duckdb_storage import DuckDBStorage
from app.domain.models.agent_output import AgentId, AgentOutput, Signal
from app.domain.models.macro import MacroOutput, MacroSignal
from app.main import create_app
from app.repositories.portfolio_repository import PortfolioRepository


def _analyst_output(agent_id, symbol, signal, score, status="OK", confidence=0.6,
                    limitations=(), factors=()):
    return AgentOutput(
        agent_id=AgentId(agent_id),
        entity_id=symbol,
        score=score,
        signal=Signal(signal),
        confidence=confidence,
        factors=list(factors),
        rationale=f"{agent_id} rationale",
        evidence=[],
        data_limitations=list(limitations),
        generated_at=datetime(2026, 9, 10, 10, 0, tzinfo=timezone.utc),
        data_version="1.0",
        provenance={},
        status=status,
    )


def _macro_output(signal="positive", score=60.0, status="OK"):
    return MacroOutput(
        requested_symbol="TCS",
        score=score,
        overall_signal=MacroSignal(signal),
        confidence=0.7,
        status=status,
        factors=[],
        rationale="Macro Environment Signal is NEUTRAL.",
        data_limitations=[],
        data_through={"repo_rate": "2026-06-05"},
        provenance={},
    )


def _full_set(symbol="TCS"):
    return dict(
        firm=_analyst_output("firm_analyst", symbol, "buy", 62.0, status="DEGRADED",
                             confidence=0.45, limitations=["No filings ingested."]),
        industry=_analyst_output("industry_analyst", symbol, "buy", 69.0, confidence=0.8),
        sentiment=_analyst_output("sentiment_analyst", symbol, "buy", 57.0, confidence=0.7),
        macro=_macro_output(),
    )


@pytest.fixture()
def agent(tmp_path):
    storage = DuckDBStorage(tmp_path / "portfolio.duckdb")
    storage.connect()
    repo = PortfolioRepository(storage)
    yield PortfolioAgent(repo), repo
    storage.close()


def test_all_positive_agrees_without_blending(agent):
    portfolio_agent, _ = agent
    out = portfolio_agent.run("TCS", persist=False, **_full_set("TCS"))

    assert out.entity_id == "TCS"
    assert out.methodology == "portfolio_agent_v1"
    assert out.agreement.verdict == "unanimous-positive"
    assert out.agreement.conflicts == []
    assert out.status == "OK"
    assert out.coverage == 1.0
    # No overall score/signal anywhere at the top level — perspectives only.
    # (Macro's own overall_signal lives nested inside its perspective entry.)
    blob = out.model_dump_json().lower()
    assert "overall_score" not in blob
    top = out.model_dump()
    assert "overall_signal" not in top and "score" not in top and "signal" not in top
    assert [p.agent_id for p in out.perspectives] == [
        "firm_analyst", "industry_analyst", "sentiment_analyst", "macro_analyst",
    ]
    # Degraded firm view is flagged as a risk with its real limitation.
    assert any("Firm Analyst is DEGRADED" in r or "DEGRADED" in r for r in out.risks)
    assert any("No filings ingested." in r for r in out.risks)
    # Evidence traces every perspective.
    assert {e.agent_id for e in out.evidence} == {
        "firm_analyst", "industry_analyst", "sentiment_analyst", "macro_analyst",
    }
    # Thesis names the company and the agreement; macro stays environmental.
    assert "TCS" in out.thesis
    assert "environment" in out.thesis.lower() or "macro" in out.thesis.lower()


def test_conflict_shown_not_hidden(agent):
    portfolio_agent, _ = agent
    views = _full_set("INFY")
    views["sentiment"] = _analyst_output(
        "sentiment_analyst", "INFY", "sell", 35.0, confidence=0.7,
        limitations=["Thin news coverage."],
    )
    out = portfolio_agent.run("INFY", persist=False, **views)

    assert out.agreement.verdict == "majority-positive"
    assert len(out.agreement.conflicts) == 3
    pairs = [set(c["between"]) for c in out.agreement.conflicts]
    assert {"Firm Analyst", "Sentiment Analyst"} in pairs
    assert {"Industry Analyst", "Sentiment Analyst"} in pairs
    assert {"Macro Analyst", "Sentiment Analyst"} in pairs
    assert all("averaged away" in c["description"] for c in out.agreement.conflicts)
    # Bear case draws on the conflict; bull case on fixing it.
    bull = next(s for s in out.scenarios if s.label == "Bull case")
    bear = next(s for s in out.scenarios if s.label == "Bear case")
    assert any("Sentiment Analyst" in c for c in bull.conditions)
    assert any("Sentiment Analyst" in c or "Firm Analyst" in c for c in bear.conditions)


def test_missing_inputs_degrade_honestly(agent):
    portfolio_agent, _ = agent
    out = portfolio_agent.run(
        "LT", persist=False,
        firm=None,
        industry=None,
        sentiment=_analyst_output("sentiment_analyst", "LT", "neutral", 50.0),
        macro=None,
    )
    assert out.status == "DEGRADED"
    assert out.coverage == 0.25
    assert out.agreement.verdict == "insufficient"
    assert any("Firm Analyst unavailable" in r for r in out.risks)
    assert any("Macro Analyst unavailable" in r for r in out.risks)
    assert "Missing perspectives" in " ".join(out.data_limitations)
    # Bull case names the concrete missing inputs.
    bull = next(s for s in out.scenarios if s.label == "Bull case")
    assert any("fundamental" in c for c in bull.conditions)


def test_nothing_available_is_unavailable(agent):
    portfolio_agent, _ = agent
    out = portfolio_agent.run("TCS", persist=False)
    assert out.status == "UNAVAILABLE"
    assert out.coverage == 0.0
    assert out.confidence == 0.0
    assert out.agreement.verdict == "insufficient"
    assert "no investment thesis can be stated" in out.thesis.lower()


def test_macro_reused_across_companies_without_recalculation():
    """Same MacroOutput object serves TCS and INFY; company views differ."""
    portfolio_agent = PortfolioAgent(None)
    shared_macro = _macro_output(signal="neutral", score=50.0)
    tcs = portfolio_agent.run(
        "TCS", persist=False,
        firm=_analyst_output("firm_analyst", "TCS", "buy", 62.0),
        industry=None, sentiment=None, macro=shared_macro,
    )
    infy = portfolio_agent.run(
        "INFY", persist=False,
        firm=_analyst_output("firm_analyst", "INFY", "sell", 35.0),
        industry=None, sentiment=None, macro=shared_macro,
    )
    assert tcs.entity_id == "TCS" and infy.entity_id == "INFY"
    macro_tcs = next(p for p in tcs.perspectives if p.agent_id == "macro_analyst")
    macro_infy = next(p for p in infy.perspectives if p.agent_id == "macro_analyst")
    assert macro_tcs.signal_label == macro_infy.signal_label == "NEUTRAL-environment"
    assert macro_tcs.score == macro_infy.score == 50.0
    # ...while the company views genuinely differ.
    firm_tcs = next(p for p in tcs.perspectives if p.agent_id == "firm_analyst")
    firm_infy = next(p for p in infy.perspectives if p.agent_id == "firm_analyst")
    assert firm_tcs.direction == "positive" and firm_infy.direction == "negative"


def test_run_persists_per_company(agent):
    portfolio_agent, repo = agent
    out = portfolio_agent.run("TCS", persist=True, **_full_set("TCS"))
    assert out.status == "OK"
    row = repo.latest("TCS")
    assert row is not None and row["entity_id"] == "TCS"
    assert repo.latest("tcs") is not None  # case-insensitive read
    assert repo.latest("INFY") is None  # nothing leaks across companies
    assert len(repo.history("TCS", limit=10)) == 1


def test_deterministic_rerun(agent):
    portfolio_agent, _ = agent
    first = portfolio_agent.run("TCS", persist=False, **_full_set("TCS"))
    second = portfolio_agent.run("TCS", persist=False, **_full_set("TCS"))
    assert first.thesis == second.thesis
    assert first.rationale == second.rationale
    assert first.confidence == second.confidence
    assert first.agreement == second.agreement


def test_api_contract(tmp_path, monkeypatch):
    from app.repositories.agent_output_repository import AgentOutputRepository
    from app.repositories.financial_repository import FinancialRepository
    from app.repositories.macro_repository import MacroRepository
    from app.repositories.market_repository import MarketRepository
    from app.services.agent_service import AgentService

    storage = DuckDBStorage(tmp_path / "portfolio_api.duckdb")
    storage.connect()

    import app.api.routes.agents as agents_routes
    import app.api.routes.portfolio as portfolio_routes

    class TestContainer:
        pass

    TestContainer.agent_service = AgentService(
        FinancialRepository(storage),
        MarketRepository(storage),
        AgentOutputRepository(storage),
    )
    TestContainer.portfolio_repo = PortfolioRepository(storage)
    monkeypatch.setattr(agents_routes, "get_container", lambda: TestContainer())
    monkeypatch.setattr(portfolio_routes, "get_container", lambda: TestContainer())
    client = TestClient(create_app())
    try:
        # Unknown company rejected at the boundary.
        r = client.post("/api/agents/portfolio/NOPE/run")
        assert r.status_code == 404

        # Empty latest before any run — honest null, not fabricated.
        r = client.get("/api/portfolio/latest?symbol=TCS")
        assert r.status_code == 200
        assert r.json() == {"count": 0, "output": None}

        # Unknown company rejected for reads too.
        r = client.get("/api/portfolio/latest?symbol=NOPE")
        assert r.status_code == 404
    finally:
        storage.close()
