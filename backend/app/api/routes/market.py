"""Market data endpoints — thin handlers delegating to MarketService."""

from __future__ import annotations

from fastapi import APIRouter

from app.core.exceptions import NotFoundError
from app.services.container import get_container

router = APIRouter(prefix="/api/market", tags=["market"])


@router.post("/refresh")
def refresh_market_data(symbols: list[str] | None = None) -> dict:
    """Refresh stored OHLCV from the market provider (whole universe by default)."""
    container = get_container()
    return container.market_service.refresh_universe(symbols)


@router.post("/refresh/{symbol}")
def refresh_symbol_data(symbol: str) -> dict:
    container = get_container()
    return container.market_service.refresh_symbol(symbol)


@router.get("/prices/{symbol}")
def get_prices(symbol: str, start: str | None = None, end: str | None = None) -> dict:
    """Stored price series with explicit LIVE/CACHED/UNAVAILABLE status."""
    from datetime import date as date_type

    container = get_container()
    start_d = date_type.fromisoformat(start) if start else None
    end_d = date_type.fromisoformat(end) if end else None
    return container.market_service.get_price_series(symbol, start_d, end_d)


@router.get("/status")
def market_data_status() -> dict:
    """Per-symbol storage status for the dashboard/data pages."""
    container = get_container()
    from app.data.universe.universe_config import get_universe

    rows = []
    for entry in get_universe():
        count = container.market_repo.count(entry.symbol)
        latest = container.market_repo.latest_trade_date(entry.symbol)
        rows.append(
            {
                "symbol": entry.symbol,
                "name": entry.name,
                "rows": count,
                "latest_trade_date": latest.isoformat() if latest else None,
                "status": "CACHED" if count else "UNAVAILABLE",
            }
        )
    return {"symbols": rows}