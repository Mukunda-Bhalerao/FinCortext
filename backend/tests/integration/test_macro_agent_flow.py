"""Integration: seeded macro observations → MacroAgent → persisted output → API.

No network. Covers full/partial/empty data paths, determinism, market-wide
identity (same result regardless of requested company), and the HTTP contract.
"""

from datetime import date, timedelta

import json

import pytest
from fastapi.testclient import TestClient

from app.agents.macro.macro_agent import MacroAgent
from app.data.storage.duckdb_storage import DuckDBStorage
from app.domain.models.macro import MacroObservation
from app.main import create_app
from app.repositories.macro_repository import MacroRepository
from app.services.agent_service import AgentService
from app.services.macro_service import MacroService
from app.repositories.financial_repository import FinancialRepository
from app.repositories.market_repository import MarketRepository
from app.repositories.agent_output_repository import AgentOutputRepository


def _obs(indicator_id, value, period_end, source_name="test source", unit="%", notes=None):
    return MacroObservation(
        indicator_id=indicator_id,
        value=value,
        unit=unit,
        period_end=period_end,
        observed_at=period_end,
        published_at=None,
        source_type="unknown",
        source_name=source_name,
        notes=notes,
    )


def _seed_full(repo: MacroRepository):
    """Realistic rich state, anchored relative to today so freshness and
    12-month windows behave deterministically whenever tests run."""
    today = date.today()
    # GDP: 5 rising quarters, latest 7.8.
    for i, v in enumerate([6.9, 8.4, 7.8, 7.8, 7.8]):
        repo.save_observations([
            _obs("gdp_real_yoy", v, today - timedelta(days=32 + 92 * (4 - i)),
                 notes="base_year=2022-23")
        ])
    # CPI: rising into target, latest 4.30.
    for i, v in enumerate([3.93, 4.38, 4.45, 4.30]):
        repo.save_observations([
            _obs("cpi_yoy", v, today - timedelta(days=10 + 30 * (3 - i)))
        ])
    # Repo: cut 25bps two months ago, hold since; stance Neutral.
    repo.save_observations([
        _obs("repo_rate", 5.50, today - timedelta(days=90), unit="%",
             notes="stance=Neutral"),
        _obs("repo_rate", 5.25, today - timedelta(days=60), unit="%",
             notes="stance=Neutral"),
        _obs("repo_rate", 5.25, today - timedelta(days=10), unit="%",
             notes="stance=Neutral"),
    ])
    # Market gauges: 70 sessions each. usd_inr rises (adverse), brent falls
    # past its floor (supportive), us10y falls past 25 bps (supportive),
    # india_vix falls past its floor (supportive) → net vote +2 → POSITIVE.
    slopes = {"usd_inr": 0.05, "brent_crude": -0.10, "us10y": -0.05, "india_vix": -0.25}
    for indicator_id in ["usd_inr", "brent_crude", "us10y", "india_vix"]:
        start = today - timedelta(days=75)
        for i in range(70):
            repo.save_observations([
                _obs(indicator_id, 100.0 + i * slopes[indicator_id],
                     start + timedelta(days=i), source_name="legacy market data",
                     unit="x")
            ])


@pytest.fixture()
def stack(tmp_path):
    storage = DuckDBStorage(tmp_path / "macro.duckdb")
    storage.connect()
    macro_repo = MacroRepository(storage)
    yield macro_repo, storage
    storage.close()


def test_full_data_ok_with_documented_signals(stack):
    macro_repo, _ = stack
    _seed_full(macro_repo)
    agent = MacroAgent(macro_repo)
    out = agent.run("TCS", persist=False)

    assert out.entity_id == "MACRO_INDIA"
    assert out.requested_symbol == "TCS"
    assert out.methodology == "macro_analyst_v1"
    assert [f.name for f in out.factors] == [
        "growth", "inflation", "interest_rates", "liquidity_credit",
        "policy", "global", "events",
    ]
    by_name = {f.name: f for f in out.factors}
    # Growth 7.8 ≥ 7.0 → POSITIVE; inflation 4.30 in (4,6] → NEUTRAL.
    assert by_name["growth"].signal.value == "positive"
    assert by_name["inflation"].signal.value == "neutral"
    # Last repo decision was a hold → NEUTRAL rates direction.
    assert by_name["interest_rates"].signal.value == "neutral"
    assert by_name["interest_rates"].value == 5.25
    # Liquidity has no series — unavailable, never proxied.
    assert not by_name["liquidity_credit"].available
    assert by_name["liquidity_credit"].signal.value == "unavailable"
    assert by_name["policy"].available
    assert by_name["events"].available
    assert out.status == "OK"
    # Votes: growth +1, inflation 0, rates 0, policy 0, global +1, events 0
    # → majority POSITIVE.
    assert out.overall_signal.value == "positive"
    assert 0.0 < out.confidence <= 1.0
    assert out.data_through  # per-indicator latest dates present
    assert "MACRO" in out.rationale or "Macro" in out.rationale
    # No stock vocabulary anywhere in a market-wide view.
    blob = out.model_dump_json().lower()
    assert "strong_buy" not in blob and '"buy"' not in blob


def test_empty_store_unavailable_without_fabrication(stack):
    macro_repo, _ = stack
    out = MacroAgent(macro_repo).run("INFY", persist=False)
    assert out.status == "UNAVAILABLE"
    assert out.overall_signal.value == "unavailable"
    assert out.confidence == 0.0
    assert out.score is None  # no midpoint invented for missing data
    assert all(not f.available for f in out.factors)
    assert out.data_through == {}


def test_score_matches_signal_and_excludes_unavailable(stack):
    """Score 50 + 50·net/n over available factors only; signal always agrees."""
    from app.agents.macro import methodology as M

    macro_repo, _ = stack
    _seed_full(macro_repo)
    out = MacroAgent(macro_repo).run("TCS", persist=False)

    assert out.score is not None
    assert 0.0 <= out.score <= 100.0
    available = [f for f in out.factors if f.available]
    # Liquidity is unavailable and must not enter the denominator.
    assert all(f.name != "liquidity_credit" for f in available)
    votes = [
        1 if f.signal.value == "positive" else -1
        if f.signal.value == "negative" else 0
        for f in available
    ]
    assert out.score == M.macro_score(votes)
    assert out.overall_signal.value == M.signal_from_macro_score(out.score)
    # Score persists alongside the signal.
    assert out.provenance["factors_available"] == len(available)


def test_evidence_references_are_unique_across_factors(stack):
    """The same stored observation is cited once — repeats are removed and
    counted, so shared repo decisions cannot look like extra evidence."""
    macro_repo, _ = stack
    _seed_full(macro_repo)
    out = MacroAgent(macro_repo).run("TCS", persist=False)

    refs = [
        (e.indicator_id, e.reference)
        for f in out.factors
        for e in f.evidence
    ]
    assert len(refs) == len(set(refs))
    assert out.provenance["evidence_duplicates_removed"] >= 0
    # Interest-rates owns the current level; policy owns the dated changes.
    rates = next(f for f in out.factors if f.name == "interest_rates")
    assert len(rates.evidence) == 1
    policy = next(f for f in out.factors if f.name == "policy")
    assert all("MPC decision" in (e.note or "") or "unchanged" in (e.note or "")
               for e in policy.evidence)


def test_thin_inputs_degraded(stack):
    macro_repo, _ = stack
    macro_repo.save_observations([_obs("cpi_yoy", 4.45, date(2026, 7, 31))])
    out = MacroAgent(macro_repo).run(persist=False)
    # Only inflation (+events from the CPI prints) available → DEGRADED.
    assert out.status == "DEGRADED"
    assert out.overall_signal.value in {"positive", "neutral", "negative"}


def test_same_result_regardless_of_requested_company(stack):
    macro_repo, _ = stack
    _seed_full(macro_repo)
    agent = MacroAgent(macro_repo)
    tcs = agent.run("TCS", persist=False)
    infy = agent.run("INFY", persist=False)
    assert tcs.overall_signal == infy.overall_signal
    assert tcs.confidence == infy.confidence
    assert tcs.rationale == infy.rationale
    assert tcs.requested_symbol == "TCS"
    assert infy.requested_symbol == "INFY"
    assert tcs.entity_id == infy.entity_id == "MACRO_INDIA"


def test_run_persists_and_history_orders(stack):
    macro_repo, _ = stack
    _seed_full(macro_repo)
    agent = MacroAgent(macro_repo)
    agent.run("TCS", persist=True)
    agent.run("TCS", persist=True)
    latest = macro_repo.latest_output()
    assert latest is not None
    assert latest["overall_signal"] in {"positive", "neutral", "negative"}
    assert len(macro_repo.history(limit=10)) == 2


def test_api_contract(tmp_path, monkeypatch):
    from app.repositories.news_repository import NewsRepository
    from app.repositories.provenance_repository import ProvenanceRepository
    from app.services.macro_service import MacroService as _MS  # noqa: F401
    from app.services.market_service import MarketService

    storage = DuckDBStorage(tmp_path / "macro_api.duckdb")
    storage.connect()
    macro_repo = MacroRepository(storage)
    _seed_full(macro_repo)

    import app.api.routes.agents as agents_routes
    import app.api.routes.macro as macro_routes

    class TestContainer:
        pass

    agent_service = AgentService(
        FinancialRepository(storage),
        MarketRepository(storage),
        AgentOutputRepository(storage),
        macro_repo=macro_repo,
    )
    macro_service = __import__(
        "app.services.macro_service", fromlist=["MacroService"]
    ).MacroService([], macro_repo, ProvenanceRepository(storage))
    TestContainer.agent_service = agent_service
    TestContainer.macro_service = macro_service
    TestContainer.macro_repo = macro_repo
    monkeypatch.setattr(agents_routes, "get_container", lambda: TestContainer())
    monkeypatch.setattr(macro_routes, "get_container", lambda: TestContainer())
    client = TestClient(create_app())
    try:
        r = client.post("/api/agents/macro/TCS/run")
        assert r.status_code == 200
        body = r.json()
        assert body["agent_id"] == "macro_analyst"
        assert body["entity_id"] == "MACRO_INDIA"
        assert body["requested_symbol"] == "TCS"
        assert body["overall_signal"] in {"positive", "neutral", "negative"}
        assert len(body["factors"]) == 7
        # Environment score present, numeric, and consistent with the signal —
        # it is still never a blended stock score (no buy/sell vocabulary).
        assert isinstance(body["score"], (int, float)) and 0 <= body["score"] <= 100
        assert body["overall_signal"] == (
            "positive" if body["score"] > 50
            else "negative" if body["score"] < 50 else "neutral"
        )
        blob = json.dumps(body).lower()
        assert "strong_buy" not in blob and '"buy"' not in blob

        r = client.get("/api/macro/latest")
        assert r.status_code == 200
        assert r.json()["count"] == 1
        assert r.json()["output"]["overall_signal"] == body["overall_signal"]

        r = client.get("/api/macro/history?limit=5")
        assert r.status_code == 200
        assert r.json()["count"] == 1

        r = client.get("/api/macro/indicators")
        assert r.status_code == 200
        ids = {row["indicator_id"] for row in r.json()["indicators"]}
        assert {"gdp_real_yoy", "cpi_yoy", "repo_rate"} <= ids

        # Unknown company still rejected at the route boundary.
        r = client.post("/api/agents/macro/NOPE/run")
        assert r.status_code == 404

        # Portfolio remains explicitly unimplemented.
        r = client.post("/api/agents/portfolio/TCS/run")
        assert r.status_code == 404
    finally:
        storage.close()
