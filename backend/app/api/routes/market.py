"""Market data endpoints — thin handlers delegating to MarketService."""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.core.exceptions import NotFoundError
from app.services.container import get_container

router = APIRouter(prefix="/api/market", tags=["market"])


@router.post("/refresh")
def refresh_market_data(symbols: list[str] | None = None) -> dict:
    """Refresh stored OHLCV from the market provider (whole universe by default)."""
    container = get_container()
    return container.market_service.refresh_universe(symbols)


@router.post("/refresh/{symbol}")
def refresh_symbol_data(symbol: str, instrument_key: str | None = Query(default=None)) -> dict:
    container = get_container()
    return container.market_service.refresh_symbol(symbol, instrument_key=instrument_key)


@router.get("/prices/{symbol}")
def get_prices(
    symbol: str,
    start: str | None = None,
    end: str | None = None,
    instrument_key: str | None = Query(default=None),
) -> dict:
    """Stored price series with explicit LIVE/CACHED/UNAVAILABLE status."""
    from datetime import date as date_type

    container = get_container()
    start_d = date_type.fromisoformat(start) if start else None
    end_d = date_type.fromisoformat(end) if end else None
    return container.market_service.get_price_series(symbol, start_d, end_d, instrument_key)


@router.get("/search")
def search_market_symbols(
    query: str = Query(alias="query", default=""),
    q: str | None = Query(default=None),
    records: int = Query(default=20, ge=1, le=30),
) -> dict:
    """Dynamic stock search through Upstox (NSE equity).

    Accepts ``?query=TCS`` (or legacy ``?q=``). Returns NSE equity instruments
    with symbol, company name, instrument_key, exchange, segment and ISIN.
    """
    container = get_container()
    effective = (query or "").strip() or (q or "").strip()
    return container.market_service.search_symbols(effective, records=records)


@router.get("/quote/{symbol}")
def get_market_quote(symbol: str, instrument_key: str | None = Query(default=None)) -> dict:
    """Current market quote (LTP, prev close, OHLC, volume, 52w high/low).

    Missing values are explicit ``None`` (frontend renders "N/A") — never 0.
    """
    container = get_container()
    return container.market_service.get_quote(symbol, instrument_key)


@router.post("/resolve")
def resolve_market_symbol(body: dict) -> dict:
    """Create/resolve the company context for a valid NSE equity.

    Body: {"symbol": "TCS", "instrument_key": "NSE_EQ|..."} — instrument_key
    optional when the symbol alone resolves via Upstox search. Persists the
    instrument metadata so later market/agent calls work without re-search.
    """
    container = get_container()
    symbol = str((body or {}).get("symbol") or "").strip()
    if not symbol:
        raise NotFoundError("Body must include 'symbol'.")
    instrument_key = (body or {}).get("instrument_key")
    key = str(instrument_key or "").strip() or None
    resolved = container.market_service.resolve_symbol(symbol, key)
    # Best-effort warm: refresh history + fetch a live quote snapshot so the
    # frontend chart/values populate immediately after selection. Failures are
    # reported honestly, never raised as 500s for a valid resolution.
    refresh: dict | None = None
    quote: dict | None = None
    try:
        refresh = container.market_service.refresh_symbol(resolved["symbol"], instrument_key=resolved.get("instrument_key"))
    except Exception as exc:
        refresh = {"status": "ERROR", "error": getattr(exc, "message", str(exc))}
    try:
        quote = container.market_service.get_quote(resolved["symbol"], resolved.get("instrument_key"))
    except Exception as exc:
        quote = {"status": "UNAVAILABLE", "error": getattr(exc, "message", str(exc))}
    return {"resolved": resolved, "refresh": refresh, "quote": quote}


@router.post("/prepare/{symbol}")
def prepare_company_data(symbol: str, body: dict | None = None) -> dict:
    """Central company preparation: resolve -> quote -> history ->
    fundamentals -> news -> peers, then report readiness.

    Called once when the user selects a stock so every analyst tab finds
    prepared data in the repositories it already reads. Body may carry
    {"instrument_key": "NSE_EQ|..."}; per-area failures are reported as
    honest UNAVAILABLE/ERROR statuses, never fabricated values.
    """
    container = get_container()
    key = None
    if isinstance(body, dict):
        key = str(body.get("instrument_key") or "").strip() or None
    return container.company_preparation_service.prepare_company(symbol, key)


@router.get("/prepared/{symbol}")
def company_readiness(symbol: str) -> dict:
    """Preparation/readiness status from stored data only (no network)."""
    container = get_container()
    return container.company_preparation_service.readiness(symbol)


@router.get("/peers/{symbol}")
def company_peers(symbol: str) -> dict:
    """Effective peer set for a company (configured + discovered)."""
    container = get_container()
    return container.company_preparation_service.company_peers(symbol)


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


@router.get("/dashboard")
def market_dashboard() -> dict:
    """Indian market overview: indices, tracked-company movers, research
    opportunities (stored analyst outputs). Real Upstox data only —
    unavailable sections degrade to explicit statuses, never fabricated."""
    container = get_container()
    return container.market_dashboard_service.get_dashboard()
