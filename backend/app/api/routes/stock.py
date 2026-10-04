"""Stock Context endpoints — thin handlers over StockContextService."""

from __future__ import annotations

from fastapi import APIRouter

from app.services.container import get_container

router = APIRouter(prefix="/api/stock", tags=["stock-context"])


@router.get("/{symbol}/context")
def stock_context(symbol: str, instrument_key: str | None = None) -> dict:
    """Complete, cached Stock Context for one NSE symbol.

    One assembly per selected symbol: resolved instrument identity, live
    quote (with market depth), stored OHLCV history, 52-week high/low,
    company profile, fundamentals coverage, and stored news. Every section
    carries an explicit status; genuinely unavailable fields are marked
    unavailable — never fabricated.
    """
    container = get_container()
    return container.stock_context_service.get_stock_context(symbol, instrument_key)


@router.get("/{symbol}")
def stock_context_alias(symbol: str, instrument_key: str | None = None) -> dict:
    """Alias of `/{symbol}/context` (frontend convenience)."""
    container = get_container()
    return container.stock_context_service.get_stock_context(symbol, instrument_key)


@router.delete("/{symbol}/context")
def invalidate_stock_context(symbol: str) -> dict:
    """Drop the cached Stock Context for one symbol (explicit refreshes)."""
    container = get_container()
    container.stock_context_service.invalidate(symbol)
    return {"symbol": symbol.upper(), "invalidated": True}
