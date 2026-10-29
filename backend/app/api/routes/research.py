from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import Services, services
from app.errors import NotFound
from app.schemas.research import ResearchHistory, ResearchItem, ResearchOverview
from app.schemas.validation import ValidationStatus

router = APIRouter(prefix="/api/research")
Svc = Annotated[Services, Depends(services)]


@router.get("")
async def overview(svc: Svc) -> ResearchOverview:
    """Latest research for every watchlist stock, plus the market-wide macro indicators."""
    return await svc.research.overview()


@router.get("/validation")
async def validation(svc: Svc) -> ValidationStatus:
    """Whether the agents' scores lined up with later returns (replay plus forward tracking)."""
    return svc.lab.status()


@router.post("/validation/run", status_code=202)
async def run_validation(svc: Svc) -> ValidationStatus:
    svc.lab.request_run(force=True)
    return svc.lab.status()


@router.get("/{symbol}")
async def report(svc: Svc, symbol: str) -> ResearchItem:
    if len(symbol) > 40:
        raise NotFound("Unknown symbol")
    return svc.research.item(svc.instruments.by_symbol(symbol))


@router.get("/{symbol}/history")
async def history(svc: Svc, symbol: str) -> ResearchHistory:
    """Stored research over time and what changed since about a day ago."""
    if len(symbol) > 40:
        raise NotFound("Unknown symbol")
    return svc.research.history(svc.instruments.by_symbol(symbol))


@router.post("/{symbol}/run", status_code=202)
async def run(svc: Svc, symbol: str) -> ResearchItem:
    """Queue a fresh run regardless of the age of the stored report."""
    if len(symbol) > 40:
        raise NotFound("Unknown symbol")
    instrument = svc.instruments.by_symbol(symbol)
    svc.research.enqueue(instrument.instrument_key, force=True)
    return svc.research.item(instrument)
