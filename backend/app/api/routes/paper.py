from typing import Annotated

from fastapi import APIRouter, Body, Depends

from app.api.deps import Services, services
from app.schemas.paper import AccountActivity, OrderIn, OrderPreview, PaperOrder

router = APIRouter(prefix="/api/tracker/{pid}")
Svc = Annotated[Services, Depends(services)]


@router.post("/orders/preview")
async def preview(svc: Svc, pid: str, req: Annotated[OrderIn, Body()]) -> OrderPreview:
    """Price, itemised charges, break-even and warnings for an order, without placing it."""
    return await svc.paper.preview(pid, req)


@router.post("/orders", status_code=201)
async def place(svc: Svc, pid: str, req: Annotated[OrderIn, Body()]) -> PaperOrder:
    """Place a paper order. It fills against live prices; nothing is sent to any broker."""
    return await svc.paper.place(pid, req)


@router.delete("/orders/{oid}")
async def cancel(svc: Svc, pid: str, oid: str) -> PaperOrder:
    return svc.paper.cancel(pid, oid)


@router.get("/activity")
async def activity(svc: Svc, pid: str) -> AccountActivity:
    """Orders, closed trades, the decision journal and the scorecard of a paper account."""
    return await svc.paper.activity(pid)
