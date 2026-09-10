"""Integration: fake fundamentals provider → service → DuckDB → Firm Agent → API.

Covers per-symbol isolation, refresh-replace (no duplicate accumulation),
partial-data honesty, provider-failure isolation, and the HTTP endpoints.
"""

from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.core.exceptions import ProviderError
from app.data.storage.duckdb_storage import DuckDBStorage
from app.domain.contracts.providers import FundamentalDataProvider
from app.main import create_app
from app.repositories.agent_output_repository import AgentOutputRepository
from app.repositories.financial_repository import FinancialRepository
from app.repositories.market_repository import MarketRepository
from app.repositories.provenance_repository import ProvenanceRepository
from app.services.agent_service import AgentService
from app.services.fundamentals_service import FundamentalsService


def _bundle(symbol, revenue=(1000.0, 900.0), income=(150.0, 120.0),
            equity=800.0, debt=200.0, pe=22.5, roe=0.19):
    annual = []
    for i, (rev, ni) in enumerate(zip(*[revenue, income])):
        period_end = date(2025 - i, 3, 31)
        annual.append({
            "period_end": period_end,
            "total_revenue": rev,
            "net_income": ni,
            "total_assets": 2000.0,
            "total_equity": equity,
            "total_debt": debt,
        })
    return {
        "symbol": symbol,
        "ticker": f"{symbol}.NS",
        "currency": "INR",
        "annual": annual,
        "snapshot": {"pe_ratio": pe, "roe": roe, "as_of": date.today().isoformat()},
        "warnings": [],
    }


class FakeFundamentalsProvider(FundamentalDataProvider):
    name = "fake_fundamentals"

    def __init__(self, bundles=None, fail_symbols=()):
        self.bundles = bundles or {}
        self.fail_symbols = set(fail_symbols)
        self.requested: list[str] = []

    def fetch_fundamentals(self, ticker: str) -> dict:
        self.requested.append(ticker)
        if ticker in self.fail_symbols:
            raise ProviderError(f"fake outage for {ticker}")
        if ticker not in self.bundles:
            raise ProviderError(f"no fixture for {ticker}")
        return self.bundles[ticker]


@pytest.fixture()
def stack(tmp_path):
    storage = DuckDBStorage(tmp_path / "fund.duckdb")
    storage.connect()
    financial_repo = FinancialRepository(storage)
    provenance_repo = ProvenanceRepository(storage)
    provider = FakeFundamentalsProvider({
        "TCS": _bundle("TCS"),
        "INFY": _bundle("INFY", revenue=(500.0, 480.0), income=(100.0, 95.0)),
    })
    service = FundamentalsService(provider, financial_repo, provenance_repo)
    agent_service = AgentService(
        financial_repo, MarketRepository(storage), AgentOutputRepository(storage)
    )
    yield service, agent_service, financial_repo, provider
    storage.close()


def test_refresh_stores_canonical_observations_with_provenance(stack):
    service, _, financial_repo, _ = stack
    result = service.refresh_symbol("TCS")
    assert result["status"] == "LIVE"
    assert result["symbol"] == "TCS"
    # 2 years × 5 annual metrics + pe + roe
    assert result["observations_stored"] == 12
    assert set(result["metrics"]) == {
        "total_revenue", "net_income", "total_assets",
        "total_equity", "total_debt", "pe_ratio", "roe",
    }
    # Canonical storage: internal symbol, provider source type, real periods.
    obs = financial_repo.get_observations("TCS", metric="total_revenue", latest_period=False)
    assert len(obs) == 2
    assert all(o.entity_id == "TCS" for o in obs)
    assert all(o.source_type.value == "yfinance" for o in obs)
    assert all("yfinance" in o.source_name for o in obs)
    assert obs[0].period_end in {date(2025, 3, 31), date(2024, 3, 31)}
    assert obs[0].unit == "INR" and obs[0].currency == "INR"
    # Snapshot ratios carry no statement period — honest point-in-time stamp.
    pe = financial_repo.latest_metric_value("TCS", "pe_ratio")
    assert pe is not None and pe.value == 22.5 and pe.period_end is None
    assert pe.available_at is not None
    assert any("Snapshot ratios" in lim for lim in result["limitations"])


def test_refresh_replaces_provider_snapshot_without_touching_filings(stack):
    from app.domain.models.financial import FinancialObservation

    service, _, financial_repo, _ = stack
    service.refresh_symbol("TCS")
    # Simulate an official filing observation for the same metric.
    financial_repo.save_observations([
        FinancialObservation(
            entity_id="TCS", metric="total_revenue", value=999.0, unit="INR",
            source_type="official_filing", source_name="Annual Report FY2025",
            period_end=date(2025, 3, 31),
        )
    ])
    before = len(financial_repo.get_observations("TCS", latest_period=False))
    result = service.refresh_symbol("TCS")
    after = len(financial_repo.get_observations("TCS", latest_period=False))
    # Same count: provider rows replaced, filing row preserved.
    assert after == before
    assert result["observations_replaced"] > 0
    filing_rows = [
        o for o in financial_repo.get_observations("TCS", latest_period=False)
        if o.source_type.value == "official_filing"
    ]
    assert len(filing_rows) == 1 and filing_rows[0].value == 999.0


def test_partial_bundle_stores_available_metrics_only(stack):
    service, _, financial_repo, provider = stack
    provider.bundles["LT"] = {
        "symbol": "LT", "ticker": "LT.NS", "currency": "INR",
        "annual": [{"period_end": date(2025, 3, 31), "total_revenue": 800.0,
                    "net_income": None, "total_assets": None,
                    "total_equity": None, "total_debt": -5.0}],
        "snapshot": {"pe_ratio": None, "roe": None, "as_of": date.today().isoformat()},
        "warnings": ["balance sheet unavailable"],
    }
    result = service.refresh_symbol("LT")
    assert result["status"] == "LIVE"
    assert result["metrics"] == ["total_revenue"]
    assert result["warnings"] == ["balance sheet unavailable"]
    # Negative debt rejected with a reason, never stored.
    assert any(r["metric"] == "total_debt" for r in result["rejected"])
    assert financial_repo.latest_metric_value("LT", "total_debt") is None


def test_per_symbol_isolation_and_failure_isolation(stack):
    service, agent_service, _, provider = stack
    provider.fail_symbols.add("INFY")
    summary = service.refresh_universe(symbols=["TCS", "INFY"])
    by_symbol = {r["symbol"]: r for r in summary["results"]}
    assert by_symbol["TCS"]["status"] == "LIVE"
    assert by_symbol["INFY"]["status"] == "ERROR"
    assert summary["symbols_ok"] == summary["symbols_requested"] - 1
    # Failed symbol left no observations behind.
    assert agent_service.list_outputs("firm_analyst", "INFY") == []
    # Firm run for TCS uses only TCS data.
    out = agent_service.run_agent("firm_analyst", "TCS")
    assert out.entity_id == "TCS"
    assert out.status in {"OK", "DEGRADED"}
    assert all("INFY" not in (e.reference or "") for e in out.evidence)


def test_firm_agent_consumes_provider_fundamentals(stack):
    service, agent_service, _, _ = stack
    service.refresh_symbol("TCS")
    out = agent_service.run_agent("firm_analyst", "TCS")
    # Full annual data: all 5 fundamental factors available (momentum missing).
    names = {f.name: f for f in out.factors}
    assert names["profitability"].available
    assert names["revenue_growth"].available
    assert names["financial_health"].available
    assert names["return_on_equity"].available
    assert names["valuation"].available
    assert not names["market_momentum"].available  # no prices seeded
    assert out.status == "OK"
    # Evidence cites the provider source, not an official filing.
    assert any("yfinance" in (e.source_name or "") for e in out.evidence)


def test_coverage_endpoint_shape(stack):
    service, _, _, _ = stack
    service.refresh_symbol("TCS")
    cov = service.get_coverage("TCS")
    assert cov["symbol"] == "TCS"
    assert cov["status"] == "CACHED"
    assert cov["has_provider"] is True
    assert cov["has_official"] is False
    assert cov["metrics"]["total_revenue"]["value"] == 1000.0
    assert cov["metrics"]["pe_ratio"]["period_end"] is None
    empty = service.get_coverage("SBIN")
    assert empty["status"] == "UNAVAILABLE"
    assert empty["metrics"] == {}


def test_http_endpoints(tmp_path, monkeypatch, stack):
    service, _, _, _ = stack
    import app.api.routes.fundamentals as fund_routes

    class TestContainer:
        pass

    TestContainer.fundamentals_service = service
    monkeypatch.setattr(fund_routes, "get_container", lambda: TestContainer())
    client = TestClient(create_app())

    r = client.post("/api/fundamentals/refresh/TCS")
    assert r.status_code == 200
    assert r.json()["symbol"] == "TCS"
    assert r.json()["status"] == "LIVE"

    r = client.get("/api/fundamentals/TCS")
    assert r.status_code == 200
    assert r.json()["metric_count"] == 7

    r = client.post("/api/fundamentals/refresh/NOPE")
    assert r.status_code == 404
