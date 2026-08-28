"""Filing parsers: CSV, XBRL/XML, and limited PDF extraction.

Each parser returns a FilingParseResult containing canonical
FinancialObservation candidates plus warnings. Parsers never invent values:
unparseable rows are reported as warnings/rejections.

PDF is a LIMITED fallback: pypdf text extraction with regex-based number
detection. Arbitrary PDF annual reports cannot be reliably parsed — the
result carries explicit quality warnings and the caller must surface them.
"""

from __future__ import annotations

import csv
import io
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import date, datetime

from app.core.exceptions import IngestionError, UnsupportedFormatError
from app.core.logging import get_logger
from app.data.ingestion.filings.metric_mapping import map_metric, map_xbrl_element
from app.domain.models.financial import (
    ConsolidationBasis,
    FinancialObservation,
    StatementType,
)

logger = get_logger("ingestion.filings")

SUPPORTED_EXTENSIONS = {".csv": "csv", ".xbrl": "xbrl", ".xml": "xbrl", ".pdf": "pdf"}


@dataclass
class FilingParseResult:
    observations: list[FinancialObservation] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    unmapped_labels: list[str] = field(default_factory=list)
    document_type: str = "csv"


def detect_file_type(file_name: str) -> str:
    """Detect supported filing type from extension."""
    lower = file_name.lower()
    for ext, doc_type in SUPPORTED_EXTENSIONS.items():
        if lower.endswith(ext):
            return doc_type
    raise UnsupportedFormatError(
        f"Unsupported filing format for '{file_name}'. "
        f"Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
    )


# --- helpers ------------------------------------------------------------------

_NUM_RE = re.compile(r"^-?[\d,]+(\.\d+)?$")


def _parse_number(raw: str) -> float | None:
    """Parse a numeric string like '1,234.56' or '(500)' (negative)."""
    text = raw.strip()
    if not text:
        return None
    negative = text.startswith("(") and text.endswith(")")
    if negative:
        text = text[1:-1]
    if not _NUM_RE.match(text.replace(" ", "")):
        return None
    try:
        value = float(text.replace(",", ""))
        return -value if negative else value
    except ValueError:
        return None


def _parse_date(raw: str) -> date | None:
    """Parse common date formats found in filings."""
    text = raw.strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d", "%d-%b-%Y", "%d %b %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _parse_datetime(raw: str | None) -> datetime | None:
    if not raw:
        return None
    d = _parse_date(raw)
    if d:
        return datetime(d.year, d.month, d.day)
    try:
        return datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
    except ValueError:
        return None


# --- CSV parser -----------------------------------------------------------------


def parse_csv(content: bytes, *, entity_id: str, source_name: str) -> FilingParseResult:
    """Parse a structured CSV filing export.

    Expected flexible schema (header row required). Recognized columns
    (case/space-insensitive): metric/label/item, value, unit, currency,
    period_start, period_end, statement_type, consolidation_basis,
    fiscal_year, filing_date, published_at.
    """
    result = FilingParseResult(document_type="csv")
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise IngestionError(f"CSV file is not valid UTF-8: {exc}") from exc

    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise IngestionError("CSV file has no header row")

    def norm(col: str) -> str:
        return col.strip().lower().replace(" ", "_")

    columns = {norm(c): c for c in reader.fieldnames}
    metric_col = next((columns[k] for k in ("metric", "label", "item") if k in columns), None)
    value_col = next((columns[k] for k in ("value", "amount") if k in columns), None)
    if metric_col is None or value_col is None:
        raise IngestionError(
            "CSV must contain 'metric' and 'value' columns "
            f"(found: {reader.fieldnames})"
        )

    def col(*names: str) -> str | None:
        for n in names:
            if n in columns:
                return columns[n]
        return None

    unit_col = col("unit")
    currency_col = col("currency")
    ps_col = col("period_start")
    pe_col = col("period_end")
    st_col = col("statement_type")
    cb_col = col("consolidation_basis")
    fy_col = col("fiscal_year")
    fd_col = col("filing_date")
    pub_col = col("published_at")

    for i, row in enumerate(reader, start=2):
        label = (row.get(metric_col) or "").strip()
        raw_value = (row.get(value_col) or "").strip()
        if not label:
            continue
        mapped = map_metric(label)
        if mapped is None:
            result.unmapped_labels.append(label)
            result.warnings.append(f"row {i}: unmapped metric label '{label}'")
            continue
        value = _parse_number(raw_value)
        if value is None:
            result.warnings.append(f"row {i}: unparseable value '{raw_value}' for '{label}'")
            continue

        canonical_metric, statement = mapped
        period_start = _parse_date(row.get(ps_col) or "") if ps_col else None
        period_end = _parse_date(row.get(pe_col) or "") if pe_col else None
        filing_date = _parse_datetime(row.get(fd_col)) if fd_col else None
        published_at = _parse_datetime(row.get(pub_col)) if pub_col else None

        try:
            result.observations.append(
                FinancialObservation(
                    entity_id=entity_id,
                    metric=canonical_metric,
                    value=value,
                    unit=(row.get(unit_col) or "INR").strip() if unit_col else "INR",
                    currency=(row.get(currency_col) or "INR").strip() if currency_col else "INR",
                    period_start=period_start,
                    period_end=period_end,
                    statement_type=StatementType(statement),
                    consolidation_basis=ConsolidationBasis(
                        (row.get(cb_col) or "unknown").strip().lower() if cb_col else "unknown"
                    ),
                    fiscal_year=(row.get(fy_col) or "").strip() or None if fy_col else None,
                    source_name=source_name,
                    filing_date=filing_date,
                    published_at=published_at,
                )
            )
        except Exception as exc:
            result.warnings.append(f"row {i}: validation failed for '{label}': {exc}")

    if not result.observations and not result.warnings:
        raise IngestionError("CSV contained no recognizable metric rows")
    return result


# --- XBRL / XML parser ------------------------------------------------------------


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def parse_xbrl(content: bytes, *, entity_id: str, source_name: str) -> FilingParseResult:
    """Parse XBRL/XML structured facts.

    Supports flat `<fact>` style exports and standard XBRL instance documents
    with contextRef periods. Only elements with a known canonical mapping are
    extracted; everything else is reported as unmapped.
    """
    result = FilingParseResult(document_type="xbrl")
    try:
        root = ET.fromstring(content)
    except ET.ParseError as exc:
        raise IngestionError(f"Invalid XML/XBRL document: {exc}") from exc

    # contextRef → period mapping (standard XBRL instance documents)
    contexts: dict[str, tuple[date | None, date | None]] = {}
    for ctx in root.iter():
        if _local_name(ctx.tag) != "context":
            continue
        ctx_id = ctx.attrib.get("id", "")
        start = end = None
        for el in ctx.iter():
            ln = _local_name(el.tag).lower()
            if ln == "startdate" and el.text:
                start = _parse_date(el.text)
            elif ln == "enddate" and el.text:
                end = _parse_date(el.text)
            elif ln == "instant" and el.text:
                start = end = _parse_date(el.text)
        contexts[ctx_id] = (start, end)

    fact_count = 0
    for element in root.iter():
        local = _local_name(element.tag)
        if local in {"context", "xbrl", "instance"} or local.endswith("schema"):
            continue
        canonical = map_xbrl_element(local)
        if canonical is None:
            continue
        raw_value = (element.text or "").strip()
        value = _parse_number(raw_value)
        if value is None:
            result.warnings.append(f"fact '{local}': unparseable value '{raw_value}'")
            continue
        fact_count += 1

        ctx_ref = element.attrib.get("contextRef", "")
        period_start, period_end = contexts.get(ctx_ref, (None, None))

        # Unit resolution from the unitRef if present, else default INR.
        unit = "INR"
        unit_ref = element.attrib.get("unitRef")
        if unit_ref:
            for u in root.iter():
                if _local_name(u.tag) == "unit" and u.attrib.get("id") == unit_ref:
                    measure = next(
                        (m.text for m in u.iter() if _local_name(m.tag) == "measure"), None
                    )
                    if measure and "shares" in measure:
                        unit = "shares"
                    elif measure and "EUR" in measure:
                        unit = "EUR"
                    elif measure and "USD" in measure:
                        unit = "USD"
                    break

        statement = "other"
        if canonical in {"total_revenue", "net_income", "operating_profit", "eps", "profit_before_tax"}:
            statement = "income_statement"
        elif canonical in {"total_assets", "total_equity", "total_debt"}:
            statement = "balance_sheet"
        elif canonical in {"roe", "roce", "pe_ratio", "operating_margin", "net_margin"}:
            statement = "other"

        result.observations.append(
            FinancialObservation(
                entity_id=entity_id,
                metric=canonical,
                value=value,
                unit=unit if canonical not in {"roe", "roce", "pe_ratio", "operating_margin", "net_margin"} else "ratio",
                currency="INR",
                period_start=period_start,
                period_end=period_end,
                statement_type=StatementType(statement),
                source_name=source_name,
                source_reference=element.attrib.get("name") or element.attrib.get("id"),
            )
        )

    if fact_count == 0:
        result.warnings.append(
            "No mapped XBRL facts found — document may use unmapped taxonomies"
        )
    return result


# --- PDF limited fallback -----------------------------------------------------------

_PDF_LINE_RE = re.compile(
    r"^(?P<label>[A-Za-z][A-Za-z &/()'-]{2,60}?)\s{1,}(?P<value>-?[\d,]+(?:\.\d+)?)$"
)


def parse_pdf(content: bytes, *, entity_id: str, source_name: str) -> FilingParseResult:
    """LIMITED PDF extraction fallback.

    Extracts text with pypdf and applies conservative label+number line
    matching. This is NOT a reliable parser for arbitrary annual reports:
    multi-column layouts, tables, and scanned images will not parse. Every
    result carries explicit quality warnings.
    """
    result = FilingParseResult(document_type="pdf")
    result.warnings.append(
        "PDF parsing is a limited fallback: only simple 'label value' text lines "
        "are detected. Structured data (CSV/XBRL) is strongly preferred."
    )
    try:
        from pypdf import PdfReader
        import io as _io

        reader = PdfReader(_io.BytesIO(content))
        if reader.is_encrypted:
            raise IngestionError("PDF is encrypted and cannot be parsed")
        pages_text = [page.extract_text() or "" for page in reader.pages]
    except IngestionError:
        raise
    except Exception as exc:
        raise IngestionError(f"PDF text extraction failed: {exc}") from exc

    extracted = 0
    for page_no, text in enumerate(pages_text, start=1):
        for line in text.splitlines():
            line = line.strip()
            match = _PDF_LINE_RE.match(line)
            if not match:
                continue
            label = match.group("label").strip()
            mapped = map_metric(label)
            if mapped is None:
                result.unmapped_labels.append(label)
                continue
            value = _parse_number(match.group("value"))
            if value is None:
                continue
            canonical, statement = mapped
            result.observations.append(
                FinancialObservation(
                    entity_id=entity_id,
                    metric=canonical,
                    value=value,
                    unit="ratio" if canonical in {"roe", "roce", "pe_ratio", "operating_margin", "net_margin"} else "INR",
                    currency="INR",
                    statement_type=StatementType(statement),
                    source_name=source_name,
                    source_reference=f"pdf-page-{page_no}",
                )
            )
            extracted += 1

    if extracted == 0:
        result.warnings.append(
            "No structured financial lines could be extracted from the PDF. "
            "Extraction is unreliable for this document — do not treat the "
            "result as complete."
        )
    return result


def parse_filing(content: bytes, file_name: str, *, entity_id: str, source_name: str) -> FilingParseResult:
    """Detect file type and dispatch to the appropriate parser."""
    doc_type = detect_file_type(file_name)
    if doc_type == "csv":
        return parse_csv(content, entity_id=entity_id, source_name=source_name)
    if doc_type == "xbrl":
        return parse_xbrl(content, entity_id=entity_id, source_name=source_name)
    if doc_type == "pdf":
        return parse_pdf(content, entity_id=entity_id, source_name=source_name)
    raise UnsupportedFormatError(f"Unsupported filing type: {doc_type}")