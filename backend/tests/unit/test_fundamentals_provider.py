"""Unit tests: the fundamentals provider seam (no network).

No provider is wired in production after the Upstox consolidation — these
tests pin the honest degradation (refresh unavailable) and the labeling of
provider-sourced snapshots (provider name + `provider` source type, filings
untouched, scoped replace without duplicate accumulation).
"""

from datetime import date

import pytest

from app.core.exceptions import ProviderUnavailableError
from app.data.storage.duckdb_storage import DuckDBStorage
from app.domain.contracts.providers import FundamentalDataProvider
from app.domain.models.base import DataSourceType
from app.domain.models.financial import FinancialObservation
from app.repositories.financial_repository import FinancialRepository
from app.repositories.provenance_repository import ProvenanceRepository
from app.services.fundamentals_service import FundamentalsService


class FakeFundamentalsProvider(FundamentalDataProvider):
    name = "fake_fundamentals"

    def __init__(self):
        self.requested: list[str] = []

    def fetch_fundamentals(self, ticker: str) -> dict:
        self.requested.append(ticker)
        return {
            "symbol": ticker.upper(),
            "ticker": f"{ticker.upper()}.NS",
            "currency": "INR",
            "annual": [
                {
                    "period_end": date(2025, 3, 31),
                    "total_revenue": 1000.0,
                    "net_income": 150.0,
                    "total_assets": 2000.0,
                    "total_equity": 800.0,
                    "total_debt": 200.0,
                }
            ],
            "snapshot": {"pe_ratio": 22.5, "roe": 0.19},
            "warnings": [],
        }


def test_no_provider_configured_reports_unavailable(tmp_path):
    storage = DuckDBStorage(tmp_path / "fund_none.duckdb")
    storage.connect()
    try:
        service = FundamentalsService(
            None, FinancialRepository(storage), ProvenanceRepository(storage)
        )
        with pytest.raises(ProviderUnavailableError):
            service.refresh_symbol("TCS")
        # Nothing was written; coverage stays honestly empty.
        cov = service.get_coverage("TCS")
        assert cov["status"] == "UNAVAILABLE"
        assert cov["metrics"] == {}
        assert cov["has_provider"] is False
    finally:
        storage.close()


def test_provider_snapshot_labeled_with_provider_name(tmp_path):
    storage = DuckDBStorage(tmp_path / "fund_label.duckdb")
    storage.connect()
    try:
        financial_repo = FinancialRepository(storage)
        provider = FakeFundamentalsProvider()
        service = FundamentalsService(provider, financial_repo, ProvenanceRepository(storage))
        result = service.refresh_symbol("TCS")
        assert result["status"] == "LIVE"
        obs = financial_repo.get_observations("TCS", metric="total_revenue", latest_period=False)
        assert len(obs) == 1
        assert obs[0].source_type == DataSourceType.PROVIDER
        assert "fake_fundamentals" in obs[0].source_name
    finally:
        storage.close()


def test_refresh_replaces_provider_snapshot_without_touching_filings(tmp_path):
    storage = DuckDBStorage(tmp_path / "fund_replace.duckdb")
    storage.connect()
    try:
        financial_repo = FinancialRepository(storage)
        service = FundamentalsService(
            FakeFundamentalsProvider(), financial_repo, ProvenanceRepository(storage)
        )
        service.refresh_symbol("TCS")
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
        assert after == before
        assert result["observations_replaced"] > 0
        filing_rows = [
            o for o in financial_repo.get_observations("TCS", latest_period=False)
            if o.source_type.value == "official_filing"
        ]
        assert len(filing_rows) == 1 and filing_rows[0].value == 999.0
    finally:
        storage.close()


def test_unknown_symbol_rejected(tmp_path):
    storage = DuckDBStorage(tmp_path / "fund_unknown.duckdb")
    storage.connect()
    try:
        service = FundamentalsService(
            FakeFundamentalsProvider(), FinancialRepository(storage), ProvenanceRepository(storage)
        )
        from app.core.exceptions import NotFoundError

        with pytest.raises(NotFoundError):
            service.refresh_symbol("NOPE")
    finally:
        storage.close()
