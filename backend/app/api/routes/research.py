"""Web-research endpoints — thin handlers over ResearchService.

READ-ONLY views over labeled research evidence (company profiles, peer
discoveries, news digests). Research is enrichment evidence, never market
data and never scored articles — see the research_reports contract.
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.services.container import get_container

router = APIRouter(prefix="/api/research", tags=["research"])


@router.get("/status")
def research_status() -> dict:
    """Research provider configuration status (configured vs UNAVAILABLE)."""
    container = get_container()
    return container.research_service.get_status()


@router.get("/verify")
def verify_research_model() -> dict:
    """Check the configured Gemini model is reachable with the configured key.

    No generation, no cost beyond one metadata call. Returns {"ok", "model",
    "error"|None} with sanitized diagnostics (never credentials).
    """
    container = get_container()
    return container.research_service.verify()


@router.get("/{symbol}")
def get_research(symbol: str, report_type: str | None = Query(default=None)) -> dict:
    """Stored research reports for one company (newest first).

    Optional `?report_type=company_profile|peer_discovery|news_digest` narrows
    to one kind. Research items carry their own sources and are clearly
    labeled — never NewsAPI articles, never FinBERT-scored.
    """
    from app.data.universe.universe_config import get_universe_entry

    container = get_container()
    entry = get_universe_entry(symbol)  # 404 for unknown symbols
    if report_type:
        report = container.research_repo.latest_report(entry.symbol, report_type)
        reports = [report] if report else []
    else:
        reports = container.research_repo.list_reports(entry.symbol)
    return {
        "symbol": entry.symbol,
        "name": entry.name,
        "count": len(reports),
        "provider": container.research_service.provider.name,
        "provider_configured": container.research_service.provider.is_configured,
        "reports": reports,
    }
