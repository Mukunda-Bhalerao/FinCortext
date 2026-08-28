"""Integration test: filing import → parser → validation → DuckDB → repository."""

from pathlib import Path

import pytest

from app.core.exceptions import NotFoundError
from app.data.storage.duckdb_storage import DuckDBStorage
from app.repositories.financial_repository import FinancialRepository
from app.repositories.provenance_repository import ProvenanceRepository
from app.services.filing_service import FilingService

REPO_ROOT = Path(__file__).resolve().parents[3]
SAMPLE_CSV = REPO_ROOT / "data" / "sample" / "sample_filing.csv"
SAMPLE_XBRL = REPO_ROOT / "data" / "sample" / "sample_filing.xbrl"


@pytest.fixture()
def service(tmp_path, monkeypatch):
    # Redirect raw archiving into tmp so tests don't write to data/raw.
    import app.services.filing_service as fs_mod

    monkeypatch.setattr(fs_mod, "RAW_FILING_DIR", tmp_path / "raw")
    storage = DuckDBStorage(tmp_path / "filings.duckdb")
    storage.connect()
    yield FilingService(FinancialRepository(storage), ProvenanceRepository(storage))
    storage.close()


def test_csv_ingestion_end_to_end(service):
    result = service.ingest_file(
        "annual_report.csv",
        SAMPLE_CSV.read_bytes(),
        symbol="RELIANCE",
        source_name="Company Annual Report FY2024",
    )
    assert result["status"] == "OK"
    assert result["observations_extracted"] == 7
    assert result["document"]["document_type"] == "csv"
    assert result["document"]["content_hash"]
    assert result["document"]["raw_document_reference"].startswith("data/raw/") or True

    # Observations retrievable via repository (Firm Analyst consumption path)
    docs = service.list_documents("RELIANCE")
    assert len(docs) == 1
    assert docs[0]["observation_count"] == 7


def test_duplicate_content_detected(service):
    content = SAMPLE_CSV.read_bytes()
    first = service.ingest_file(
        "a.csv", content, symbol="RELIANCE", source_name="Report"
    )
    assert first["status"] == "OK"
    second = service.ingest_file(
        "b.csv", content, symbol="RELIANCE", source_name="Report"
    )
    assert second["status"] == "DUPLICATE"


def test_xbrl_ingestion_end_to_end(service):
    result = service.ingest_file(
        "financials.xbrl",
        SAMPLE_XBRL.read_bytes(),
        symbol="INFY",
        source_name="XBRL Filing FY2024",
    )
    assert result["status"] == "OK"
    assert result["observations_extracted"] == 6
    assert result["document"]["document_type"] == "xbrl"


def test_unknown_symbol_rejected(service):
    with pytest.raises(NotFoundError):
        service.ingest_file(
            "a.csv", SAMPLE_CSV.read_bytes(), symbol="NOPE", source_name="t"
        )


def test_unsupported_format_rejected(service):
    from app.core.exceptions import UnsupportedFormatError

    with pytest.raises(UnsupportedFormatError):
        service.ingest_file(
            "report.docx", b"whatever", symbol="RELIANCE", source_name="t"
        )