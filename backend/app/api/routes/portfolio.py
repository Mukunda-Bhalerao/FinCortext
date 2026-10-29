from typing import Annotated

from fastapi import APIRouter, Body, Depends, Query

from app.api.deps import Services, services
from app.schemas.insights import Brief
from app.schemas.plan import (
    BrokerStatus,
    GoalProjection,
    GoalRequest,
    HoldingIn,
    HoldingOut,
    ObjectiveInfo,
    PortfolioPlan,
    PortfolioSummary,
    Preferences,
)
from app.schemas.portfolio import PortfolioStatus
from app.tools.objectives import OBJECTIVES

router = APIRouter(prefix="/api/portfolio")
Svc = Annotated[Services, Depends(services)]


@router.get("")
async def portfolio(svc: Svc) -> PortfolioStatus:
    """Latest watchlist portfolio analysis; queues a run when it is missing or stale."""
    svc.portfolio.request_run()
    return svc.portfolio.status()


@router.post("/run", status_code=202)
async def run(svc: Svc) -> PortfolioStatus:
    svc.portfolio.request_run(force=True)
    return svc.portfolio.status()


@router.get("/objectives")
async def objectives() -> list[ObjectiveInfo]:
    return [
        ObjectiveInfo(key=o.key, label=o.label, tagline=o.tagline, method=o.method)  # type: ignore[arg-type]
        for o in OBJECTIVES.values()
    ]


@router.get("/preferences")
async def get_preferences(svc: Svc) -> Preferences:
    return svc.portfolio.preferences()


@router.put("/preferences")
async def put_preferences(svc: Svc, prefs: Preferences) -> Preferences:
    return svc.portfolio.save_preferences(prefs)


@router.post("/plan")
async def plan(
    svc: Svc,
    prefs: Annotated[Preferences, Body()],
    save: Annotated[bool, Query()] = False,
) -> PortfolioPlan:
    """Weights, risk, backtest, stress replays and trades for one objective and set of stocks."""
    if save:
        svc.portfolio.save_preferences(prefs)
    return await svc.portfolio.plan(prefs)


@router.post("/goal")
async def goal(svc: Svc, req: GoalRequest) -> GoalProjection:
    """Range of outcomes for a target amount and date, resampled from the plan's history."""
    return await svc.portfolio.goal(req)


@router.get("/summary")
async def summary(svc: Svc) -> PortfolioSummary:
    """Holdings with value, cost, P&L, weights and the broker sync status."""
    return await svc.portfolio.summary()


@router.post("/holdings/sync")
async def sync_holdings(svc: Svc) -> BrokerStatus:
    """Read holdings from Upstox (read-only; FinCortext never places orders)."""
    return await svc.portfolio.sync_broker()


@router.get("/holdings")
async def get_holdings(svc: Svc) -> list[HoldingOut]:
    return await svc.portfolio.holdings()


@router.put("/holdings")
async def put_holdings(
    svc: Svc, items: Annotated[list[HoldingIn], Body(max_length=200)]
) -> list[HoldingOut]:
    svc.portfolio.set_holdings(items)
    return await svc.portfolio.holdings()


@router.get("/brief")
async def brief(svc: Svc) -> Brief:
    """What matters now: headline, ranked insights with their facts, optional written note."""
    return await svc.assistant.brief()
