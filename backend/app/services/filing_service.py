"""Filing ingestion service: parse → validate → store → provenance.

Orchestrates official-document ingestion. Raw file bytes are archived under
`data/raw/filings/` so the raw document reference is preserved.
"""

from __future__ import annotations

import hashlib
from datetime import datetime

from app.core.config import REPO_ROOT
from app.core.exceptions import IngestionError, NotFoundError
from app.core.logging import get_logger
from app.data.ingestion.filings.parsers import (
    FilingParseResult,
    detect_file_type,
    parse_filing,
)
from app.data.universe.universe_config import get_universe_entry
from app.domain.models.financial import FilingDocument
from app.repositories.financial_repository import FinancialRepository
from app.repositories.provenance_repository import ProvenanceRepository

logger = get_logger("services.filing")

RAW_FILING_DIR = REPO_ROOT / "data" / "raw" / "filings"


class FilingService:
    def __init__(
        self,
        financial_repo: FinancialRepository,
        provenance_repo: ProvenanceRepository,
    ):
        self.financial_repo = financial_repo
        self.provenance_repo = provenance_repo

    def ingest_file(
        self,
        file_name: str,
        content: bytes,
        *,
        symbol: str,
        source_name: str,
        filing_date: datetime | None = None,
        published_at: datetime | None = None,
    ) -> dict:
        """Ingest one official filing file end-to-end."""
        entry = get_universe_entry(symbol)  # raises NotFoundError for unknown
        content_hash = hashlib.sha256(content).hexdigest()

        # Duplicate detection by content hash.
        if self.financial_repo.document_exists_by_hash(content_hash):
            return {
                "status": "DUPLICATE",
                "message": "A document with identical content was already ingested.",
                "content_hash": content_hash,
                "symbol": entry.symbol,
            }

        doc_type = detect_file_type(file_name)
        parse_result: FilingParseResult = parse_filing(
            content, file_name, entity_id=entry.symbol, source_name=source_name
        )

        # Attach point-in-time metadata to every observation.
        for obs in parse_result.observations:
            obs.filing_date = filing_date or obs.filing_date
            obs.published_at = published_at or obs.published_at
            obs.content_hash = content_hash

        # Archive raw file (best effort — ingestion continues if archiving fails).
        raw_ref = self._archive_raw(file_name, content, entry.symbol, content_hash)

        document = FilingDocument(
            document_id=f"doc-{content_hash[:16]}",
            entity_id=entry.symbol,
            document_type=doc_type,
            file_name=file_name,
            file_path=raw_ref,
            content_hash=content_hash,
            source_name=source_name,
            filing_date=filing_date,
            published_at=published_at,
            observation_count=len(parse_result.observations),
            parse_warnings=parse_result.warnings,
        )

        saved = 0
        if parse_result.observations:
            saved = self.financial_repo.save_observations(parse_result.observations)
        self.financial_repo.save_document(document)
        self.provenance_repo.record(
            "filing_ingested",
            entity_id=entry.symbol,
            source_type="official_filing",
            source_name=source_name,
            content_hash=content_hash,
            rows_ingested=saved,
            rows_rejected=len(parse_result.warnings),
            detail=f"document_type={doc_type}; file={file_name}",
        )
        logger.info(
            "Filing ingested: %s (%s) → %d observations, %d warnings",
            file_name, entry.symbol, saved, len(parse_result.warnings),
        )

        status = "OK" if saved else "NO_DATA"
        return {
            "status": status,
            "symbol": entry.symbol,
            "document": {
                "document_id": document.document_id,
                "document_type": doc_type,
                "file_name": file_name,
                "content_hash": content_hash,
                "raw_document_reference": raw_ref,
                "source_name": source_name,
                "filing_date": filing_date.isoformat() if filing_date else None,
                "published_at": published_at.isoformat() if published_at else None,
            },
            "observations_extracted": saved,
            "warnings": parse_result.warnings,
            "unmapped_labels": parse_result.unmapped_labels[:20],
            "limitations": (
                [
                    "PDF extraction is a limited fallback; verify values against "
                    "the original document."
                ]
                if doc_type == "pdf"
                else []
            ),
        }

    def _archive_raw(self, file_name: str, content: bytes, symbol: str, content_hash: str) -> str:
        try:
            RAW_FILING_DIR.mkdir(parents=True, exist_ok=True)
            safe_name = file_name.replace("/", "_").replace("\\", "_")
            path = RAW_FILING_DIR / f"{symbol}_{content_hash[:12]}_{safe_name}"
            path.write_bytes(content)
            try:
                return str(path.relative_to(REPO_ROOT))
            except ValueError:
                # Archive dir outside the repo (e.g. tests) — store absolute path.
                return str(path)
        except OSError as exc:
            logger.warning("Raw filing archive failed for %s: %s", file_name, exc)
            return f"unarchived:{file_name}"

    def list_documents(self, symbol: str | None = None) -> list[dict]:
        if symbol:
            get_universe_entry(symbol)
        return self.financial_repo.get_documents(symbol)