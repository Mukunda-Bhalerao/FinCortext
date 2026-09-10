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


@router.get("/{symbol}")
def fundamentals_coverage(symbol: str) -> dict:
    """Latest metric coverage for one symbol, with per-metric source labels."""
    container = get_container()
    return container.fundamentals_service.get_coverage(symbol)
