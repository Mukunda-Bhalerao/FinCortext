"""Fundamentals endpoints — thin handlers over FundamentalsService."""

from __future__ import annotations

from fastapi import APIRouter

from app.services.container import get_container

router = APIRouter(prefix="/api/fundamentals", tags=["fundamentals"])


@router.post("/refresh")
def refresh_fundamentals(symbols: list[str] | None = None) -> dict:
    """Refresh provider fundamentals (whole universe by default).

    Supplements — never replaces — ingested official filings. Every stored
    observation is labeled with its provider source.
    """
    container = get_container()
    return container.fundamentals_service.refresh_universe(symbols)


@router.post("/refresh/{symbol}")
def refresh_symbol_fundamentals(symbol: str) -> dict:
    container = get_container()
    return container.fundamentals_service.refresh_symbol(symbol)


@router.post("/enrich/{symbol}")
def enrich_symbol_fundamentals(symbol: str) -> dict:
    """Labeled web-research fundamentals enrichment for one symbol.

    Used when no provider fundamentals exist and no stored observations are
    available (e.g. dynamically searched equities). Values are WEB-RESEARCHED
    and stored with source_type=web_research so the UI distinguishes them
    from provider/official data. Cached and rate-limited (one research per
    symbol per 10 minutes).
    """
    container = get_container()
    return container.research_service.enrich_fundamentals(
        symbol, financial_repo=container.financial_repo
    )


@router.get("/{symbol}")
def fundamentals_coverage(symbol: str) -> dict:
    """Latest metric coverage for one symbol, with per-metric source labels."""
    container = get_container()
    return container.fundamentals_service.get_coverage(symbol)
