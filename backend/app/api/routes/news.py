"""News endpoints — thin handlers over NewsService."""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.services.container import get_container

router = APIRouter(prefix="/api/news", tags=["news"])


@router.get("/status")
def news_status() -> dict:
    """News provider configuration status (LIVE-capable vs UNAVAILABLE)."""
    container = get_container()
    return container.news_service.get_status()


@router.post("/refresh/{symbol}")
def refresh_news(
    symbol: str,
    days: int = Query(default=7, ge=1, le=30),
    page_size: int = Query(default=50, ge=1, le=100),
) -> dict:
    """Fetch live news for a universe entity (requires NEWS_API_KEY).

    Missing key / provider failures return explicit UNAVAILABLE/ERROR status
    dicts — the endpoint never fabricates articles and never crashes.
    """
    container = get_container()
    return container.news_service.refresh_entity_news(
        symbol, days=days, page_size=page_size
    )


@router.get("/{symbol}")
def get_news(symbol: str, limit: int = Query(default=50, ge=1, le=200)) -> dict:
    """Stored (cached) articles for an entity with explicit data status."""
    container = get_container()
    return container.news_service.get_entity_news(symbol, limit=limit)