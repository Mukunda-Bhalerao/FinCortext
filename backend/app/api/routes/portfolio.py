"""Portfolio endpoints — thin handlers over AgentService + PortfolioRepository.

Synthesis runs go through the standard agent route
(`POST /api/agents/portfolio/{symbol}/run`); these endpoints cover the
per-company synthesis history.
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.services.container import get_container

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])


@router.get("/latest")
def portfolio_latest(symbol: str = Query(...)) -> dict:
    """Latest stored portfolio synthesis for one company, if any."""
    from app.data.universe.universe_config import get_universe_entry

    entry = get_universe_entry(symbol)  # validate symbol
    container = get_container()
    view = container.portfolio_repo.latest_view(entry.symbol)
    if view is None:
        return {"count": 0, "output": None}
    return {"count": 1, "output": view}


@router.get("/history")
def portfolio_history(
    symbol: str = Query(...), limit: int = Query(default=20, ge=1, le=100)
) -> dict:
    """Stored portfolio syntheses for one company, newest first."""
    from app.data.universe.universe_config import get_universe_entry

    entry = get_universe_entry(symbol)  # validate symbol
    container = get_container()
    rows = container.portfolio_repo.history(entry.symbol, limit=limit)
    return {"count": len(rows), "outputs": rows}
