from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response

from app.api.deps import Services, services
from app.errors import NotFound
from app.schemas.market import (
    CandleSeries,
    Instrument,
    LabeledQuote,
    MarketStatus,
    Movers,
    NewsFeed,
    StockSummary,
    Timeframe,
)

router = APIRouter(prefix="/api")
Svc = Annotated[Services, Depends(services)]
Key = Annotated[str, Query(min_length=3, max_length=64, description="Provider instrument key")]


@router.get("/market/status")
async def market_status(svc: Svc) -> MarketStatus:
    await svc.clock.refresh()
    return svc.clock.status()


@router.get("/market/indices")
async def indices(svc: Svc) -> list[LabeledQuote]:
    return await svc.market.indices()


@router.get("/market/sectors")
async def sectors(svc: Svc) -> list[LabeledQuote]:
    return await svc.market.sectors()


@router.get("/market/movers")
async def movers(svc: Svc) -> Movers:
    return await svc.market.movers()


@router.get("/instruments/search")
async def search(
    svc: Svc,
    q: Annotated[str, Query(min_length=1, max_length=40)],
    limit: Annotated[int, Query(ge=1, le=50)] = 15,
) -> list[Instrument]:
    return svc.instruments.search(q, limit)


@router.get("/instruments/lookup")
async def lookup(svc: Svc, key: Key) -> Instrument:
    return svc.instruments.get(key)


@router.get("/stocks/{symbol}")
async def stock(svc: Svc, symbol: str) -> StockSummary:
    if len(symbol) > 40:
        raise NotFound("Unknown symbol")
    return await svc.market.summary(svc.instruments.by_symbol(symbol))


@router.get("/candles")
async def candles(svc: Svc, key: Key, tf: Timeframe = "1D") -> CandleSeries:
    svc.instruments.get(key)  # only instruments from the master reach the provider
    return await svc.candles.series(key, tf)


@router.get("/watchlist")
async def watchlist(svc: Svc) -> list[LabeledQuote]:
    return await svc.market.watchlist()


@router.put("/watchlist", status_code=204)
async def watch(svc: Svc, key: Key) -> Response:
    svc.market.watch(key)
    svc.research.enqueue(key)
    return Response(status_code=204)


@router.delete("/watchlist", status_code=204)
async def unwatch(svc: Svc, key: Key) -> Response:
    svc.market.unwatch(key)
    return Response(status_code=204)


@router.get("/news")
async def news(svc: Svc) -> NewsFeed:
    return await svc.news.latest()
