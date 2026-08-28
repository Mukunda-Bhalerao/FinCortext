"""Unit tests for filing parsers using bundled sample fixtures."""

from datetime import date
from pathlib import Path

import pytest

from app.core.exceptions import IngestionError, UnsupportedFormatError
from app.data.ingestion.filings.metric_mapping import map_metric, map_xbrl_element
from app.data.ingestion.filings.parsers import (
    detect_file_type,
    parse_csv,
    parse_pdf,
    parse_xbrl,
    _parse_number,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
SAMPLE_CSV = REPO_ROOT / "data" / "sample" / "sample_filing.csv"
SAMPLE_XBRL = REPO_ROOT / "data" / "sample" / "sample_filing.xbrl"


# --- helpers -----------------------------------------------------------------


def test_parse_number_formats():
    assert _parse_number("1,234.56") == 1234.56
    assert _parse_number("(500)") == -500.0
    assert _parse_number(" 42 ") == 42.0
    assert _parse_number("N/A") is None
    assert _parse_number("") is None


def test_metric_mapping():
    assert map_metric("Profit After Tax") == ("net_income", "income_statement")
    assert map_metric("  total   revenue ") == ("total_revenue", "income_statement")
    assert map_metric("Unknown Widget Count") is None
    assert map_xbrl_element("Revenues") == "total_revenue"
    assert map_xbrl_element("StockholdersEquity") == "total_equity"


def test_detect_file_type():
    assert detect_file_type("a.CSV") == "csv"
    assert detect_file_type("b.xbrl") == "xbrl"
    assert detect_file_type("c.xml") == "xbrl"
    assert detect_file_type("d.pdf") == "pdf"
    with pytest.raises(UnsupportedFormatError):
        detect_file_type("e.docx")


# --- CSV parser -----------------------------------------------------------------


def test_parse_csv_sample_fixture():
    result = parse_csv(
        SAMPLE_CSV.read_bytes(), entity_id="RELIANCE", source_name="Sample Annual Report"
    )
    metrics = {o.metric: o for o in result.observations}
    assert set(metrics) >= {
        "total_revenue", "net_income", "operating_profit",
        "total_assets", "total_equity", "total_debt", "eps",
    }
    rev = metrics["total_revenue"]
    assert rev.value == 2392000
    assert rev.unit == "INR_cr"
    assert rev.period_end == date(2024, 3, 31)
    assert rev.statement_type.value == "income_statement"
    assert rev.consolidation_basis.value == "consolidated"
    assert rev.fiscal_year == "FY2024"
    assert rev.available_at is not None  # point-in-time resolved
    assert result.warnings == []


def test_parse_csv_reports_unmapped_and_bad_values():
    csv_text = (
        "metric,value\n"
        "Total Revenue,1000\n"
        "Mystery Metric,5\n"
        "Net Income,not-a-number\n"
    )
    result = parse_csv(csv_text.encode(), entity_id="X", source_name="t")
    assert len(result.observations) == 1
    assert any("unmapped" in w for w in result.warnings)
    assert any("unparseable" in w for w in result.warnings)


def test_parse_csv_rejects_missing_columns():
    with pytest.raises(IngestionError):
        parse_csv(b"foo,bar\n1,2\n", entity_id="X", source_name="t")


def test_parse_csv_rejects_invalid_utf8():
    with pytest.raises(IngestionError):
        parse_csv(b"\xff\xfe\x00", entity_id="X", source_name="t")


# --- XBRL parser -----------------------------------------------------------------


def test_parse_xbrl_sample_fixture():
    result = parse_xbrl(
        SAMPLE_XBRL.read_bytes(), entity_id="RELIANCE", source_name="Sample XBRL"
    )
    metrics = {o.metric: o for o in result.observations}
    assert "total_revenue" in metrics
    assert metrics["total_revenue"].value == 2392000
    assert metrics["total_revenue"].period_start == date(2023, 4, 1)
    assert metrics["total_revenue"].period_end == date(2024, 3, 31)
    assert "total_assets" in metrics
    assert metrics["total_assets"].period_end == date(2024, 3, 31)  # instant context
    assert metrics["total_revenue"].unit == "INR"
    assert result.warnings == []


def test_parse_xbrl_invalid_xml():
    with pytest.raises(IngestionError):
        parse_xbrl(b"<not-xml", entity_id="X", source_name="t")


def test_parse_xbrl_no_mapped_facts_warns():
    xml = b'<?xml version="1.0"?><root><thing>5</thing></root>'
    result = parse_xbrl(xml, entity_id="X", source_name="t")
    assert result.observations == []
    assert any("No mapped XBRL facts" in w for w in result.warnings)


# --- PDF limited fallback ------------------------------------------------------------


def test_parse_pdf_simple_lines(tmp_path):
    # Build a tiny PDF with pypdf-friendly text via reportlab-free approach:
    # pypdf cannot create PDFs, so we test the regex path through a minimal
    # hand-built PDF containing one text line.
    pdf_bytes = _minimal_pdf_with_text("Total Revenue 2392000\n")
    result = parse_pdf(pdf_bytes, entity_id="RELIANCE", source_name="t")
    assert any("limited fallback" in w for w in result.warnings)
    assert any(o.metric == "total_revenue" for o in result.observations)


def test_parse_pdf_reports_unextractable(tmp_path):
    pdf_bytes = _minimal_pdf_with_text("random unstructured content 123 abc\n")
    result = parse_pdf(pdf_bytes, entity_id="RELIANCE", source_name="t")
    assert result.observations == []
    assert any("unreliable" in w for w in result.warnings)


def _minimal_pdf_with_text(text: str) -> bytes:
    """Build a tiny valid single-page PDF containing one text line."""
    stream = f"BT /F1 12 Tf 50 700 Td ({text.strip()}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref_pos = len(out)
    out += f"xref\n0 {len(objects)+1}\n".encode()
    out += b"0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects)+1} /Root 1 0 R >>\n"
        f"startxref\n{xref_pos}\n%%EOF".encode()
    )
    return bytes(out)