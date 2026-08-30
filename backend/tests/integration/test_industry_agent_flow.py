"""Integration: seeded multi-symbol prices → IndustryAgent → persisted output → API."""

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from app.core.exceptions import ProviderError
from app.data.storage.duckdb_storage import DuckDBStorage
from app.domain.contracts.providers import MarketDataProvider
from app.domain.models.market import MarketPrice
from app.main import create_app
from app.repositories.agent_output_repository import AgentOutputRepository
from app.repositories.financial_repository import FinancialRepository
from app.repositories.market_repository import MarketRepository
from app.repositories.provenance_repository import ProvenanceRepository
from app.services.agent_service import AgentService
from app.services.market_service import MarketService


def _seed_series(market_repo: MarketRepository, symbol: str, daily: float, days=100):
    prices = []
    d = date(2024, 1, 1)
    price = 100.0
    while len(prices) < days:
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


@pytest.fixture()
def stack(tmp_path):
    storage = DuckDBStorage(tmp_path / "industry.duckdb")
    storage.connect()
    market_repo = MarketRepository(storage)
    financial_repo = FinancialRepository(storage)
    output_repo = AgentOutputRepository(storage)
    agent_service = AgentService(financial_repo, market_repo, output_repo)
    yield agent_service, market_repo, financial_repo
    storage.close()


def test_industry_agent_relative_strength(stack):
    agent_service, market_repo, financial_repo = stack
    # TCS +5%/day (strong), INFY +1%/day (peer median), TCS is the subject.
    _seed_series(market_repo, "TCS", 0.005)
    _seed_series(market_repo, "INFY", 0.001)

    output = agent_service.run_agent("industry_analyst", "TCS")
    assert output.agent_id.value == "industry_analyst"
    assert output.score is not None and 0 <= output.score <= 100
    assert output.status == "OK"
    assert output.provenance["sector"] == "Information Technology"
    assert output.provenance["peer_count"] == 1

    # Relative strength: TCS momentum > INFY momentum → high points
    rs = next(f for f in output.factors if f.name == "relative_strength")
    assert rs.available and rs.value is not None and rs.value > 0
    # Peer momentum available from INFY prices
    pm = next(f for f in output.factors if f.name == "peer_momentum")
    assert pm.available
    # Fundamentals missing (no filings) → limitation listed, not fabricated
    pf = next(f for f in output.factors if f.name == "peer_fundamentals")
    assert not pf.available
    assert any("filings" in lim for lim in output.data_limitations)
    # Deterministic
    out2 = agent_service.run_agent("industry_analyst", "TCS", persist=False)
    assert out2.score == output.score


def test_industry_agent_no_data_unavailable(stack):
    agent_service, _, _ = stack
    output = agent_service.run_agent("industry_analyst", "TCS")
    assert output.score is None
    assert output.status == "UNAVAILABLE"
    assert output.signal.value == "unavailable"


def test_industry_agent_api_endpoint(tmp_path, monkeypatch, stack):
    agent_service, market_repo, _ = stack
    _seed_series(market_repo, "TCS", 0.005)
    _seed_series(market_repo, "INFY", 0.001)

    import app.api.routes.agents as agents_routes

    class TestContainer:
        pass

    TestContainer.agent_service = agent_service
    monkeypatch.setattr(agents_routes, "get_container", lambda: TestContainer())
    client = TestClient(create_app())

    r = client.post("/api/agents/industry/TCS/run")
    assert r.status_code == 200
    body = r.json()
    assert body["agent_id"] == "industry_analyst"
    assert body["score"] is not None
    assert len(body["factors"]) == 4

    r = client.get("/api/agents/outputs?agent_id=industry_analyst&symbol=TCS")
    assert r.status_code == 200
    assert r.json()["count"] == 1


# --- automatic market-data preparation ---------------------------------------


class RecordingProvider(MarketDataProvider):
    """Deterministic fake provider that records requested tickers (no network).

    Generates 60 weekday bars ending at `end` (today) so refreshed symbols
    count as sufficient fresh cache for subsequent runs.
    """

    name = "recording"

    def __init__(self, fail: bool = False):
        self.fail = fail
        self.requested: list[str] = []

    def fetch_ohlcv(self, ticker: str, start: date, end: date) -> list[MarketPrice]:
        self.requested.append(ticker)
        if self.fail:
            raise ProviderError("simulated provider outage")
        bars = []
        price = 100.0
        d = end
        while len(bars) < 60 and d >= start:
            if d.weekday() < 5:
                bars.append(
                    MarketPrice(
                        symbol=ticker,
                        provider_ticker=f"{ticker}.NS",
                        trade_date=d,
                        open=price,
                        high=price * 1.01,
                        low=price * 0.99,
                        close=price,
                        volume=1000,
                    )
                )
                price *= 1.001
            d -= timedelta(days=1)
        return list(reversed(bars))


def test_industry_agent_auto_prepares_missing_peer_data(tmp_path):
    """Running the Industry Analyst fetches missing sector-peer price history
    via the normal provider pipeline, then analyses; a re-run reuses the cache."""
    storage = DuckDBStorage(tmp_path / "prep.duckdb")
    storage.connect()
    market_repo = MarketRepository(storage)
    provider = RecordingProvider()
    market_service = MarketService(provider, market_repo, ProvenanceRepository(storage))
    agent_service = AgentService(
        FinancialRepository(storage),
        market_repo,
        AgentOutputRepository(storage),
        market_service=market_service,
    )

    output = agent_service.run_agent("industry_analyst", "TCS")

    # TCS and its IT-sector peer INFY were fetched automatically (empty cache).
    assert provider.requested == ["TCS", "INFY"]
    # Peer factors computable from the prepared data; filings still missing.
    assert output.status == "OK"  # 3/4 factors, weight 0.75 >= 0.5
    assert output.provenance["peers_with_prices"] == ["INFY"]
    prep = {p["symbol"]: p["action"] for p in output.provenance["data_preparation"]}
    assert prep == {"TCS": "refreshed", "INFY": "refreshed"}

    # Second run: sufficient fresh cache — provider is NOT called again.
    calls_after_first = len(provider.requested)
    output2 = agent_service.run_agent("industry_analyst", "TCS", persist=False)
    assert len(provider.requested) == calls_after_first
    assert output2.score == output.score
    prep2 = {p["symbol"]: p["action"] for p in output2.provenance["data_preparation"]}
    assert prep2 == {"TCS": "cached", "INFY": "cached"}
    storage.close()


def test_industry_agent_prep_failure_still_runs_with_cached_data(tmp_path):
    """If peer data cannot be fetched (provider outage), the agent still runs
    on whatever cached data exists and reports missing peers honestly."""
    storage = DuckDBStorage(tmp_path / "prep_fail.duckdb")
    storage.connect()
    market_repo = MarketRepository(storage)
    # Company has sufficient FRESH cached history; peer history is missing.
    today = date.today()
    market_repo.upsert_bars(
        [
            MarketPrice(
                symbol="TCS",
                provider_ticker="TCS.NS",
                trade_date=today - timedelta(days=i + 1),
                open=100.0,
                high=110.0,
                low=95.0,
                close=100.0 + i,
                volume=1000,
            )
            for i in range(12)
        ]
    )
    provider = RecordingProvider(fail=True)
    market_service = MarketService(provider, market_repo, ProvenanceRepository(storage))
    agent_service = AgentService(
        FinancialRepository(storage),
        market_repo,
        AgentOutputRepository(storage),
        market_service=market_service,
    )

    output = agent_service.run_agent("industry_analyst", "TCS")

    # Preparation attempted the peer fetch and reported the failure (no raise).
    prep = {p["symbol"]: p["action"] for p in output.provenance["data_preparation"]}
    assert prep == {"TCS": "cached", "INFY": "refresh_failed"}
    # The company's own cached data was still used; peer factors unavailable.
    assert output.provenance["peers_with_prices"] == []
    assert output.status == "UNAVAILABLE"
    assert any("peer" in lim.lower() for lim in output.data_limitations)
    storage.close()