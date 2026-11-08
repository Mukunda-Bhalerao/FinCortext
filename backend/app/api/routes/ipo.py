from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import Services, services
from app.schemas.ipo import IpoDetail, IpoOverview

router = APIRouter(prefix="/api/ipo")
Svc = Annotated[Services, Depends(services)]


@router.get("")
async def overview(svc: Svc) -> IpoOverview:
    """Open, upcoming, awaiting-listing and recently listed NSE IPOs with demand and results."""
    return await svc.ipo.overview()


@router.get("/{symbol}")
async def issue(svc: Svc, symbol: str) -> IpoDetail:
    return await svc.ipo.issue(symbol)
