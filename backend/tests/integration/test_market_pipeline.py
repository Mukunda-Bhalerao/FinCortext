"""Integration test: fake provider → validation → DuckDB → repository → API."""

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from app.core.exceptions import ProviderError
from app.data.storage.duckdb_storage import DuckDBStorage
from app.domain.contracts.providers import MarketDataProvider
from app.domain.models.market import MarketPrice
from app.main import create_app
from app.repositories.market_repository import MarketRepository
from app.repositories.provenance_repository import ProvenanceRepository
from app.services.market_service import MarketService


class FakeMarketProvider(MarketDataProvider):
    """Deterministic fake provider (no network)."""

    name = "fake_market"

    def __init__(self, fail: bool = False):
        self.fail = fail

    def fetch_ohlcv(self, ticker: str, start: date, end: date) -> list[MarketPrice]:
        if self.fail:
            raise ProviderError("simulated provider outage")
        bars = []
        price = 100.0
        d = start
        while d <= end:
            if d.weekday() < 5:  # skip weekends
                bars.append(
                    MarketPrice(
                        symbol=ticker.split(".")[0],
                        provider_ticker=ticker,
                        trade_date=d,
                        open=price,
                        high=price * 1.02,
                        low=price * 0.98,
                        close=price * 1.01,
                        volume=10_000,
                    )
                )
                price *= 1.01
            d += timedelta(days=1)
        return bars


@pytest.fixture()
def service(tmp_path):
    storage = DuckDBStorage(tmp_path / "mkt.duckdb")
    storage.connect()
    yield MarketService(FakeMarketProvider(), MarketRepository(storage), ProvenanceRepository(storage))
    storage.close()


def test_refresh_and_read_pipeline(service):
    result = service.refresh_symbol("RELIANCE", start=date(2024, 1, 1), end=date(2024, 1, 31))
    assert result["status"] == "LIVE"
    assert result["rows_stored"] > 15

    series = service.get_price_series("RELIANCE")
    assert series["count"] == result["rows_stored"]
    assert series["prices"][0]["close"] > 0
    # Deterministic fake: closes rise monotonically.
    closes = [p["close"] for p in series["prices"]]
    assert closes == sorted(closes)


def test_provider_failure_is_isolated_and_reported(tmp_path):
    storage = DuckDBStorage(tmp_path / "mkt2.duckdb")
    storage.connect()
    service = MarketService(
        FakeMarketProvider(fail=True), MarketRepository(storage), ProvenanceRepository(storage)
    )
    summary = service.refresh_universe(["RELIANCE", "TCS"])
    assert summary["symbols_ok"] == 0
    assert all(r["status"] == "ERROR" for r in summary["results"])
    storage.close()


def test_universe_and_prices_api(tmp_path, monkeypatch):
    # Build an app whose container uses a temp DB and fake provider.
    import app.services.container as container_mod

    storage = DuckDBStorage(tmp_path / "api.duckdb")
    storage.connect()

    class TestContainer(container_mod.Container):
        def __init__(self):
            self.storage = storage
            self.market_repo = MarketRepository(storage)
            self.financial_repo = None
            self.news_repo = None
            self.agent_output_repo = None
            self.universe_repo = None
            self.provenance_repo = ProvenanceRepository(storage)
            self.market_provider = FakeMarketProvider()
            from app.data.universe.universe_config import get_universe

            self.market_service = MarketService(
                self.market_provider, self.market_repo, self.provenance_repo
            )
            # Pre-seed data so /prices returns rows without network.
            self.market_service.refresh_symbol("RELIANCE", date(2024, 1, 1), date(2024, 1, 10))

    # Patch where the route modules actually look it up (imported at module
    # import time), not just in the container module.
    import app.api.routes.market as market_routes

    monkeypatch.setattr(market_routes, "get_container", lambda: TestContainer())

    app = create_app()
    client = TestClient(app)

    # Universe endpoint
    r = client.get("/api/universe")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 10
    assert any(e["symbol"] == "RELIANCE" for e in body["entries"])

    # Unknown symbol → 404 with domain error shape
    r = client.get("/api/universe/NOPE")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"

    # Prices endpoint (seeded via fake provider)
    r = client.get("/api/market/prices/RELIANCE")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] > 0
    assert body["status"] in {"LIVE", "CACHED"}
    assert body["prices"][0]["close"] > 0