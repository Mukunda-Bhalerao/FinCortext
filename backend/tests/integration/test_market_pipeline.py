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


def test_refresh_stores_bars_under_internal_symbol(tmp_path):
    """Regression: refresh must store bars under the canonical INTERNAL symbol.

    The real yfinance adapter keys bars by the ticker string it receives, so
    the service must request the internal symbol (the provider resolves the
    provider ticker via the universe mapping). Storing rows under 'TCS.NS'
    while every read path queries 'TCS' produced '501 stored' from the
    refresh yet 0 rows / UNAVAILABLE on read.
    """

    class EchoTickerProvider(MarketDataProvider):
        """Mimics the real adapter: canonical symbol = ticker it was given."""

        name = "echo_ticker"

        def __init__(self):
            self.requested: list[str] = []

        def fetch_ohlcv(self, ticker: str, start: date, end: date) -> list[MarketPrice]:
            self.requested.append(ticker)
            return [
                MarketPrice(
                    symbol=ticker.upper(),
                    provider_ticker=ticker,
                    trade_date=start,
                    open=100.0,
                    high=110.0,
                    low=95.0,
                    close=105.0,
                    volume=1000,
                )
            ]

    storage = DuckDBStorage(tmp_path / "mkt_key.duckdb")
    storage.connect()
    provider = EchoTickerProvider()
    service = MarketService(provider, MarketRepository(storage), ProvenanceRepository(storage))

    result = service.refresh_symbol("TCS", start=date(2024, 1, 2), end=date(2024, 1, 2))

    assert result["rows_stored"] == 1
    # The service asks for the internal symbol; the provider maps it to .NS.
    assert provider.requested == ["TCS"]
    # Rows are readable under the internal symbol — and stored only there.
    series = service.get_price_series("TCS")
    assert series["count"] == 1
    assert series["status"] in {"LIVE", "CACHED"}
    assert MarketRepository(storage).count("TCS.NS") == 0
    storage.close()


def test_normalize_symbol_keys_repairs_miskeyed_rows(tmp_path):
    """Regression: the idempotent repair re-keys provider-ticker rows."""
    storage = DuckDBStorage(tmp_path / "mkt_fix.duckdb")
    storage.connect()
    repo = MarketRepository(storage)
    miskeyed = [
        MarketPrice(
            symbol="TCS.NS", provider_ticker="TCS.NS", trade_date=date(2024, 1, 2),
            open=100.0, high=110.0, low=95.0, close=105.0, volume=1000,
        ),
        MarketPrice(
            symbol="TCS.NS", provider_ticker="TCS.NS", trade_date=date(2024, 1, 3),
            open=100.0, high=110.0, low=95.0, close=106.0, volume=1000,
        ),
    ]
    repo.upsert_bars(miskeyed)
    assert repo.count("TCS") == 0

    assert repo.normalize_symbol_keys({"TCS.NS": "TCS"}) == 2

    assert repo.count("TCS") == 2
    assert repo.count("TCS.NS") == 0
    assert repo.get_prices("TCS")[0].close == 105.0
    # Idempotent: a second pass changes nothing.
    assert repo.normalize_symbol_keys({"TCS.NS": "TCS"}) == 0
    assert repo.count("TCS") == 2
    storage.close()


def test_normalize_symbol_keys_dedups_conflicting_dates(tmp_path):
    """Rows whose trade_date already exists under the internal symbol are
    exact duplicates; the repair keeps the canonical row."""
    storage = DuckDBStorage(tmp_path / "mkt_dedup.duckdb")
    storage.connect()
    repo = MarketRepository(storage)
    repo.upsert_bars(
        [
            MarketPrice(
                symbol="TCS", provider_ticker="TCS.NS", trade_date=date(2024, 1, 2),
                open=100.0, high=110.0, low=95.0, close=105.0, volume=1000,
            )
        ]
    )
    repo.upsert_bars(
        [
            MarketPrice(
                symbol="TCS.NS", provider_ticker="TCS.NS", trade_date=date(2024, 1, 2),
                open=100.0, high=110.0, low=95.0, close=105.0, volume=1000,
            )
        ]
    )

    assert repo.normalize_symbol_keys({"TCS.NS": "TCS"}) == 0

    assert repo.count("TCS") == 1
    assert repo.count("TCS.NS") == 0
    storage.close()


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


class RecordingMarketProvider(MarketDataProvider):
    """Deterministic provider that records requested tickers (no network).

    Generates ~15 weekday bars ending at `end` (today) so refreshed symbols
    count as fresh cache for subsequent calls.
    """

    name = "recording_market"

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
        while len(bars) < 15 and d >= start:
            if d.weekday() < 5:
                bars.append(
                    MarketPrice(
                        symbol=ticker,
                        provider_ticker=f"{ticker}.NS",
                        trade_date=d,
                        open=price,
                        high=price * 1.02,
                        low=price * 0.98,
                        close=price * 1.01,
                        volume=10_000,
                    )
                )
                price *= 1.01
            d -= timedelta(days=1)
        return list(reversed(bars))


def _seed_fresh_bars(repo: MarketRepository, symbol: str, count: int = 12) -> None:
    today = date.today()
    bars = [
        MarketPrice(
            symbol=symbol,
            provider_ticker=f"{symbol}.NS",
            trade_date=today - timedelta(days=i + 1),
            open=100.0,
            high=110.0,
            low=95.0,
            close=100.0 + i,
            volume=1000,
        )
        for i in range(count)
    ]
    repo.upsert_bars(bars)


def test_ensure_history_serves_sufficient_fresh_cache_without_fetch(tmp_path):
    """Sufficient, fresh cached rows are reused — the provider is NOT called."""
    storage = DuckDBStorage(tmp_path / "ensure1.duckdb")
    storage.connect()
    repo = MarketRepository(storage)
    provider = RecordingMarketProvider()
    service = MarketService(provider, repo, ProvenanceRepository(storage))
    _seed_fresh_bars(repo, "TCS", 12)

    prepared = service.ensure_history(["TCS"], min_bars=10)

    assert prepared == [
        {"symbol": "TCS", "action": "cached", "rows": 12, "status": "CACHED"}
    ]
    assert provider.requested == []  # no unnecessary fetch
    storage.close()


def test_ensure_history_fetches_only_missing_symbols(tmp_path):
    """Missing symbols go through the normal refresh pipeline; cached ones are kept."""
    storage = DuckDBStorage(tmp_path / "ensure2.duckdb")
    storage.connect()
    repo = MarketRepository(storage)
    provider = RecordingMarketProvider()
    service = MarketService(provider, repo, ProvenanceRepository(storage))
    _seed_fresh_bars(repo, "TCS", 12)

    prepared = service.ensure_history(["TCS", "INFY"], min_bars=10)

    assert provider.requested == ["INFY"]  # TCS was cached, only INFY fetched
    by_symbol = {p["symbol"]: p for p in prepared}
    assert by_symbol["TCS"]["action"] == "cached"
    assert by_symbol["INFY"]["action"] == "refreshed"
    assert by_symbol["INFY"]["status"] == "LIVE"
    assert repo.count("INFY") >= 10

    # Second call: everything is now sufficient fresh cache — no new fetches.
    prepared2 = service.ensure_history(["TCS", "INFY"], min_bars=10)
    assert provider.requested == ["INFY"]
    assert all(p["action"] == "cached" for p in prepared2)
    storage.close()


def test_ensure_history_refreshes_stale_cache(tmp_path):
    """Cached-but-stale history (latest bar older than the LIVE window) is refreshed."""
    storage = DuckDBStorage(tmp_path / "ensure3.duckdb")
    storage.connect()
    repo = MarketRepository(storage)
    provider = RecordingMarketProvider()
    service = MarketService(provider, repo, ProvenanceRepository(storage))
    # 12 rows but latest trade date is 30 days old → stale.
    stale_bars = [
        MarketPrice(
            symbol="TCS",
            provider_ticker="TCS.NS",
            trade_date=date.today() - timedelta(days=31 - i),
            open=100.0,
            high=110.0,
            low=95.0,
            close=100.0,
            volume=1000,
        )
        for i in range(12)
    ]
    repo.upsert_bars(stale_bars)

    prepared = service.ensure_history(["TCS"], min_bars=10)

    assert provider.requested == ["TCS"]
    assert prepared[0]["action"] == "refreshed"
    assert prepared[0]["status"] == "LIVE"
    storage.close()


def test_ensure_history_isolates_provider_failure(tmp_path):
    """Provider failures are reported per symbol — never raised — so agent
    runs can proceed with whatever cached data exists."""
    storage = DuckDBStorage(tmp_path / "ensure4.duckdb")
    storage.connect()
    repo = MarketRepository(storage)
    provider = RecordingMarketProvider(fail=True)
    service = MarketService(provider, repo, ProvenanceRepository(storage))
    _seed_fresh_bars(repo, "TCS", 12)  # TCS cached; INFY must be fetched and fails

    prepared = service.ensure_history(["TCS", "INFY"], min_bars=10)

    by_symbol = {p["symbol"]: p for p in prepared}
    assert by_symbol["TCS"]["action"] == "cached"
    assert by_symbol["INFY"]["action"] == "refresh_failed"
    assert by_symbol["INFY"]["status"] == "ERROR"
    assert "outage" in by_symbol["INFY"]["error"]
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