from typing import Annotated

from fastapi import APIRouter, Body, Depends, Query, Response

from app.api.deps import Services, services
from app.schemas.tracker import (
    Period,
    PortfolioIn,
    PortfolioSummaryRow,
    PositionIn,
    QuantityIn,
    RenameIn,
    Review,
    TrackedPortfolio,
)

router = APIRouter(prefix="/api/tracker")
Svc = Annotated[Services, Depends(services)]


@router.get("")
async def list_portfolios(svc: Svc) -> list[PortfolioSummaryRow]:
    return await svc.tracker.summaries()


@router.post("", status_code=201)
async def create(svc: Svc, req: Annotated[PortfolioIn, Body()]) -> TrackedPortfolio:
    pid = svc.tracker.create(req.name, req.kind, req.starting_cash, req.plan)
    return await svc.tracker.portfolio(pid)


@router.get("/{pid}")
async def get_portfolio(svc: Svc, pid: str) -> TrackedPortfolio:
    return await svc.tracker.portfolio(pid)


@router.patch("/{pid}")
async def rename(svc: Svc, pid: str, req: Annotated[RenameIn, Body()]) -> TrackedPortfolio:
    svc.tracker.rename(pid, req.name)
    return await svc.tracker.portfolio(pid)


@router.delete("/{pid}", status_code=204)
async def delete(svc: Svc, pid: str) -> Response:
    svc.tracker.delete(pid)
    return Response(status_code=204)


@router.post("/{pid}/positions", status_code=201)
async def add_position(svc: Svc, pid: str, req: Annotated[PositionIn, Body()]) -> TrackedPortfolio:
    """Add a stock at the live price, or at a past day's close (or your own price)."""
    await svc.tracker.add_position(pid, req)
    return await svc.tracker.portfolio(pid)


@router.patch("/{pid}/positions/{position_id}")
async def set_quantity(
    svc: Svc, pid: str, position_id: str, req: Annotated[QuantityIn, Body()]
) -> TrackedPortfolio:
    svc.tracker.set_quantity(pid, position_id, req.quantity)
    return await svc.tracker.portfolio(pid)


@router.delete("/{pid}/positions/{position_id}")
async def remove_position(svc: Svc, pid: str, position_id: str) -> TrackedPortfolio:
    svc.tracker.remove_position(pid, position_id)
    return await svc.tracker.portfolio(pid)


@router.get("/{pid}/review")
async def review(
    svc: Svc,
    pid: str,
    period: Annotated[Period, Query()] = "last_visit",
    narrate: Annotated[bool, Query()] = False,
) -> Review:
    """What happened over the period and why, stock by stock, with the evidence."""
    return await svc.tracker.review(pid, period, narrate)


@router.post("/{pid}/viewed", status_code=204)
async def viewed(svc: Svc, pid: str) -> Response:
    """Mark the portfolio as seen now; the next "since your last visit" review starts here."""
    svc.tracker.mark_viewed(pid)
    return Response(status_code=204)
