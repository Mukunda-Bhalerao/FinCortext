from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import Services, services
from app.errors import NotFound
from app.schemas.research import ResearchItem, ResearchOverview

router = APIRouter(prefix="/api/research")
Svc = Annotated[Services, Depends(services)]


@router.get("")
async def overview(svc: Svc) -> ResearchOverview:
    """Latest research for every watchlist stock, plus the market-wide macro indicators."""
    return await svc.research.overview()


@router.get("/{symbol}")
async def report(svc: Svc, symbol: str) -> ResearchItem:
    if len(symbol) > 40:
        raise NotFound("Unknown symbol")
    return svc.research.item(svc.instruments.by_symbol(symbol))


@router.post("/{symbol}/run", status_code=202)
async def run(svc: Svc, symbol: str) -> ResearchItem:
    """Queue a fresh run regardless of the age of the stored report."""
    if len(symbol) > 40:
        raise NotFound("Unknown symbol")
    instrument = svc.instruments.by_symbol(symbol)
    svc.research.enqueue(instrument.instrument_key, force=True)
    return svc.research.item(instrument)
