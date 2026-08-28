"""Universe endpoints — thin route handlers over the universe config/repo."""

from __future__ import annotations

from fastapi import APIRouter

from app.data.universe.universe_config import UNIVERSE_VERSION, get_universe, get_universe_entry

router = APIRouter(prefix="/api/universe", tags=["universe"])


@router.get("")
def list_universe() -> dict:
    entries = get_universe()
    return {
        "universe_version": UNIVERSE_VERSION,
        "count": len(entries),
        "entries": [e.model_dump() for e in entries],
    }


@router.get("/{symbol}")
def get_symbol(symbol: str) -> dict:
    entry = get_universe_entry(symbol)
    return {"universe_version": UNIVERSE_VERSION, "entry": entry.model_dump()}