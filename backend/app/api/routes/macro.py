"""Macro endpoints — thin handlers over MacroService / MacroRepository.

Analysis runs go through the standard agent route
(`POST /api/agents/macro/{symbol}/run`); these endpoints cover macro data
management and the market-wide output history.
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.services.container import get_container

router = APIRouter(prefix="/api/macro", tags=["macro"])


@router.post("/data/refresh")
def refresh_macro_data(indicator_ids: list[str] | None = None) -> dict:
    """Refresh stored macro indicators (all by default, per-indicator isolation)."""
    container = get_container()
    return container.macro_service.refresh_all(indicator_ids)


@router.post("/data/refresh/{indicator_id}")
def refresh_macro_indicator(indicator_id: str) -> dict:
    container = get_container()
    return container.macro_service.refresh_indicator(indicator_id)


@router.get("/indicators")
def macro_indicator_coverage() -> dict:
    """Per-indicator storage summary for status displays."""
    container = get_container()
    return container.macro_service.get_coverage()


@router.get("/series/{indicator_id}")
def macro_series(indicator_id: str) -> dict:
    """Stored series for one indicator with explicit status."""
    container = get_container()
    return container.macro_service.get_series(indicator_id)


@router.get("/latest")
def macro_latest() -> dict:
    """Latest stored macro environment view (market-wide, shared by all companies)."""
    container = get_container()
    row = container.macro_repo.latest_output()
    if row is None:
        return {"count": 0, "output": None}
    return {"count": 1, "output": container.macro_service.latest_view()}


@router.get("/history")
def macro_history(limit: int = Query(default=20, ge=1, le=100)) -> dict:
    """Stored macro environment views, newest first."""
    container = get_container()
    rows = container.macro_repo.history(limit=limit)
    return {"count": len(rows), "outputs": rows}
