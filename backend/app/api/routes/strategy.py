from typing import Annotated

from fastapi import APIRouter, Body, Depends, Response

from app.api.deps import Services, services
from app.schemas.strategy import BacktestIn, BacktestResult, ForwardIn, Strategy, StrategyIn

router = APIRouter(prefix="/api/lab")
Svc = Annotated[Services, Depends(services)]


@router.post("/backtest")
async def backtest(svc: Svc, req: Annotated[BacktestIn, Body()]) -> BacktestResult:
    """Test trading rules on past daily prices, stock by stock, with charges."""
    return await svc.lab_rules.backtest(req)


@router.get("/strategies")
async def strategies(svc: Svc) -> list[Strategy]:
    return svc.lab_rules.all()


@router.post("/strategies", status_code=201)
async def save(svc: Svc, req: Annotated[StrategyIn, Body()]) -> Strategy:
    return svc.lab_rules.save(req)


@router.delete("/strategies/{sid}", status_code=204)
async def delete(svc: Svc, sid: str) -> Response:
    svc.lab_rules.delete(sid)
    return Response(status_code=204)


@router.post("/strategies/{sid}/start")
async def start(svc: Svc, sid: str, req: Annotated[ForwardIn, Body()]) -> Strategy:
    """Run the rules forward in a paper account: checked after each session's close."""
    return svc.lab_rules.start(sid, req)


@router.post("/strategies/{sid}/stop")
async def stop(svc: Svc, sid: str) -> Strategy:
    return svc.lab_rules.stop(sid)
