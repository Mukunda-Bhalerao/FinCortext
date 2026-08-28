"""Filing ingestion endpoints — thin handlers over FilingService."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, File, Form, UploadFile

from app.services.container import get_container

router = APIRouter(prefix="/api/filings", tags=["filings"])


@router.post("/import")
async def import_filing(
    file: UploadFile = File(...),
    symbol: str = Form(...),
    source_name: str = Form(...),
    filing_date: str | None = Form(None),
    published_at: str | None = Form(None),
) -> dict:
    """Ingest an official financial file (CSV/XBRL/XML/PDF-limited)."""
    container = get_container()
    content = await file.read()
    filing_dt = datetime.fromisoformat(filing_date) if filing_date else None
    published_dt = datetime.fromisoformat(published_at) if published_at else None
    return container.filing_service.ingest_file(
        file.filename or "unknown",
        content,
        symbol=symbol,
        source_name=source_name,
        filing_date=filing_dt,
        published_at=published_dt,
    )


@router.get("")
def list_filings(symbol: str | None = None) -> dict:
    container = get_container()
    docs = container.filing_service.list_documents(symbol)
    return {"count": len(docs), "documents": docs}