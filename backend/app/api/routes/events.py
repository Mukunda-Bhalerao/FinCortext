from typing import Annotated

from fastapi import APIRouter, Body, Depends, Query
from pydantic import BaseModel

from app.api.deps import Services, services

router = APIRouter(prefix="/api/events")
Svc = Annotated[Services, Depends(services)]


class SeenRequest(BaseModel):
    ids: list[str] | None = None


@router.get("")
async def events(svc: Svc, limit: Annotated[int, Query(ge=1, le=100)] = 40) -> dict:
    """What FinCortext noticed: research changes, unusual moves, drift, risk, data issues."""
    items, unread = svc.watcher.recent(limit)
    return {"events": items, "unread": unread}


@router.post("/seen", status_code=204)
async def seen(svc: Svc, req: Annotated[SeenRequest, Body()]) -> None:
    svc.watcher.mark_seen(req.ids)


@router.post("/check")
async def check(svc: Svc) -> dict:
    """Run the checks now instead of waiting for the next ten-minute pass."""
    return {"added": await svc.watcher.check()}
