import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.deps import Services
from app.api.routes import market, system, ws
from app.config import Settings, get_settings
from app.db import Database
from app.errors import AppError, app_error_handler
from app.providers.upstox import UpstoxProvider
from app.providers.upstox_feed import UpstoxFeed
from app.services.auth import AuthService
from app.services.candles import CandleService
from app.services.instruments import InstrumentService
from app.services.live import LiveHub
from app.services.market import MarketService
from app.services.news import NewsService
from app.services.quotes import QuoteService
from app.services.session import SessionClock

REFERENCE_REFRESH_SECONDS = 6 * 3600


class _RedactQuery(logging.Filter):
    """Drop query strings from access logs (the OAuth callback carries a one-time code)."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple) and len(record.args) >= 3:
            args = list(record.args)
            if isinstance(args[2], str) and "?" in args[2]:
                args[2] = args[2].split("?", 1)[0] + "?…"
                record.args = tuple(args)
        return True


def _configure_logging(level: str) -> None:
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    for noisy in ("httpx", "httpcore", "websockets"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").addFilter(_RedactQuery())


def build_services(settings: Settings, db: Database | None = None) -> Services:
    db = db or Database(settings.db_path)
    auth = AuthService(db, settings)
    provider = UpstoxProvider(auth.current_token, auth.mark_rejected)
    clock = SessionClock(provider)
    hub = LiveHub(provider, UpstoxFeed(provider), auth, clock, settings)
    instruments = InstrumentService(db, provider)
    quotes = QuoteService(provider, hub, clock)
    candles = CandleService(db, provider, clock)
    return Services(
        settings=settings,
        db=db,
        provider=provider,
        auth=auth,
        clock=clock,
        hub=hub,
        instruments=instruments,
        quotes=quotes,
        candles=candles,
        market=MarketService(db, instruments, quotes, candles),
        news=NewsService(db, settings.news_enabled),
    )


async def _reference_data_loop(svc: Services) -> None:
    await svc.auth.verify(svc.provider)
    while True:
        await svc.instruments.refresh_if_needed()
        await asyncio.sleep(REFERENCE_REFRESH_SECONDS)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    _configure_logging(settings.log_level)
    svc = build_services(settings)
    app.state.services = svc
    svc.hub.start()
    loader = asyncio.create_task(_reference_data_loop(svc))
    try:
        yield
    finally:
        loader.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await loader
        await svc.hub.stop()
        await svc.provider.aclose()
        svc.db.close()


def create_app() -> FastAPI:
    app = FastAPI(title="FinCortext", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=get_settings().allowed_origins,
        allow_methods=["GET", "PUT", "POST", "DELETE"],
        allow_headers=["Content-Type"],
    )
    app.add_exception_handler(AppError, app_error_handler)
    app.include_router(system.router)
    app.include_router(market.router)
    app.include_router(ws.router)
    return app


app = create_app()
