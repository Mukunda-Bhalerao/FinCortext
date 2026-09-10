"""Integration: filing ingestion → DuckDB → FirmAgent → persisted output → API."""

from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.data.storage.duckdb_storage import DuckDBStorage
from app.main import create_app
from app.repositories.agent_output_repository import AgentOutputRepository
from app.repositories.financial_repository import FinancialRepository
from app.repositories.market_repository import MarketRepository
from app.repositories.provenance_repository import ProvenanceRepository
from app.services.agent_service import AgentService
from app.services.filing_service import FilingService

REPO_ROOT = Path(__file__).resolve().parents[3]
SAMPLE_CSV = REPO_ROOT / "data" / "sample" / "sample_filing.csv"


@pytest.fixture()
def stack(tmp_path, monkeypatch):
    import app.services.filing_service as fs_mod

    monkeypatch.setattr(fs_mod, "RAW_FILING_DIR", tmp_path / "raw")
    storage = DuckDBStorage(tmp_path / "flow.duckdb")
    storage.connect()
    financial_repo = FinancialRepository(storage)
    market_repo = MarketRepository(storage)
    output_repo = AgentOutputRepository(storage)
    filing_service = FilingService(financial_repo, ProvenanceRepository(storage))
    agent_service = AgentService(financial_repo, market_repo, output_repo)
    yield filing_service, agent_service, market_repo
    storage.close()


def _seed_prices(market_repo: MarketRepository, days=100):
    prices = []
    d = date(2024, 1, 1)
    price = 100.0
    while len(prices) < days:
        if d.weekday() < 5:
            prices.append(
                __import__("app.domain.models.market", fromlist=["MarketPrice"]).MarketPrice(
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
            price *= 1.002
        d += timedelta(days=1)
    market_repo.upsert_bars(prices)


def test_filing_to_firm_output_end_to_end(stack):
    filing_service, agent_service, market_repo = stack
    # 1. Ingest official filing
    result = filing_service.ingest_file(
        "annual.csv", SAMPLE_CSV.read_bytes(), symbol="RELIANCE",
        source_name="Annual Report FY2024",
    )
    assert result["status"] == "OK"

    # 2. Seed market prices (fake deterministic series)
    _seed_prices(market_repo)

    # 3. Run Firm Agent
    output = agent_service.run_agent("firm_analyst", "RELIANCE")
    assert output.score is not None
    assert output.status == "OK"
    assert output.confidence > 0.5
    # Sample filing has one period → growth unavailable
    assert any(f.name == "revenue_growth" and not f.available for f in output.factors)
    # Momentum available from seeded prices
    assert any(f.name == "market_momentum" and f.available for f in output.factors)

    # 4. Output persisted and retrievable
    rows = agent_service.list_outputs("firm_analyst", "RELIANCE")
    assert len(rows) == 1
    assert rows[0]["score"] == output.score


def test_firm_agent_api_endpoint(tmp_path, monkeypatch, stack):
    filing_service, agent_service, market_repo = stack
    filing_service.ingest_file(
        "annual.csv", SAMPLE_CSV.read_bytes(), symbol="RELIANCE", source_name="t"
    )
    _seed_prices(market_repo)

    import app.api.routes.agents as agents_routes

    class TestContainer:
        pass

    TestContainer.agent_service = agent_service

    monkeypatch.setattr(agents_routes, "get_container", lambda: TestContainer())
    client = TestClient(create_app())

    r = client.post("/api/agents/firm/RELIANCE/run")
    assert r.status_code == 200
    body = r.json()
    assert body["agent_id"] == "firm_analyst"
    assert body["entity_id"] == "RELIANCE"
    assert body["score"] is not None
    assert body["signal"] in {"buy", "neutral", "strong_buy", "sell", "strong_sell"}
    assert len(body["factors"]) == 6
    assert body["rationale"]

    # History endpoint
    r = client.get("/api/agents/outputs?agent_id=firm_analyst&symbol=RELIANCE")
    assert r.status_code == 200
    assert r.json()["count"] == 1

    # Unimplemented agent rejected explicitly
    r = client.post("/api/agents/macro/RELIANCE/run")
    assert r.status_code == 404
    assert "not implemented" in r.json()["error"]["message"]


def test_firm_agent_per_symbol_isolation(stack):
    """Sequential runs for different symbols use only each symbol's data:
    momentum-only DEGRADED where filings are missing, full OK where the
    filing was ingested — never cross-contamination, never fabrication."""
    from app.domain.models.market import MarketPrice

    filing_service, agent_service, market_repo = stack

    def seed(symbol, start_price, daily):
        prices, d, price = [], date(2024, 1, 1), start_price
        while len(prices) < 100:
            if d.weekday() < 5:
                prices.append(
                    MarketPrice(
                        symbol=symbol,
                        provider_ticker=f"{symbol}.NS",
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
        market_repo.upsert_bars(prices)

    seed("TCS", 100.0, 0.005)   # strong momentum
    seed("INFY", 100.0, -0.004)  # weak momentum
    filing_service.ingest_file(
        "annual.csv", SAMPLE_CSV.read_bytes(), symbol="RELIANCE",
        source_name="Annual Report FY2024",
    )
    seed("RELIANCE", 100.0, 0.002)

    tcs = agent_service.run_agent("firm_analyst", "TCS")
    infy = agent_service.run_agent("firm_analyst", "INFY")
    rel = agent_service.run_agent("firm_analyst", "RELIANCE")

    assert (tcs.entity_id, infy.entity_id, rel.entity_id) == ("TCS", "INFY", "RELIANCE")
    # No filings for TCS/INFY → momentum-only DEGRADED, fundamentals unavailable
    for out in (tcs, infy):
        assert out.status == "DEGRADED"
        assert sum(1 for f in out.factors if f.available) == 1
        assert next(f for f in out.factors if f.name == "market_momentum").available
    # Opposite momenta produce opposite momentum values (not copied).
    mom = lambda o: next(f for f in o.factors if f.name == "market_momentum").value
    assert mom(tcs) is not None and mom(infy) is not None and mom(tcs) > 0 > mom(infy)
    # RELIANCE has the ingested filing → fuller coverage and OK status.
    assert rel.status == "OK"
    assert any(f.name == "profitability" and f.available for f in rel.factors)
    # History stays per symbol.
    assert len(agent_service.list_outputs("firm_analyst", "TCS")) == 1
    assert len(agent_service.list_outputs("firm_analyst", "INFY")) == 1
    assert agent_service.list_outputs("firm_analyst", "HDFCBANK") == []