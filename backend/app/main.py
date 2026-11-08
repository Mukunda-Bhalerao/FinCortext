import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.deps import Services
from app.api.routes import (
    assistant,
    events,
    ipo,
    market,
    portfolio,
    research,
    system,
    tracker,
    ws,
)
from app.config import Settings, get_settings
from app.db import Database
from app.errors import AppError, app_error_handler
from app.providers.ollama import OllamaClient
from app.providers.upstox import UpstoxProvider, parse_holding
from app.providers.upstox_feed import UpstoxFeed
from app.providers.yahoo import YahooProvider
from app.services.assistant import Assistant
from app.services.auth import AuthService
from app.services.candles import CandleService
from app.services.instruments import InstrumentService
from app.services.ipo import IpoService
from app.services.live import LiveHub
from app.services.llm_budget import LLMBudget
from app.services.market import MarketService
from app.services.monitor import SourceMonitor
from app.services.news import NewsService
from app.services.portfolio import PortfolioService
from app.services.quotes import QuoteService
from app.services.research import ResearchService
from app.services.research_data import ResearchData
from app.services.session import SessionClock
from app.services.signal_lab import SignalLab
from app.services.tracker import TrackerService
from app.services.watcher import Watcher

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
    market = MarketService(db, instruments, quotes, candles)
    llm = None
    budget = LLMBudget(db, settings.llm_daily_calls)
    if settings.llm_provider == "ollama" and settings.ollama_model:
        llm = OllamaClient(
            settings.ollama_url,
            settings.ollama_model,
            settings.ollama_api_key.get_secret_value(),
            before=budget.check,
            after=budget.record,
        )
    monitor = SourceMonitor()
    data = ResearchData(db, instruments, candles, quotes, YahooProvider(), monitor)

    def followed_keys() -> list[str]:
        """Watchlist plus every stock held in a tracked portfolio: kept researched and watched."""
        tracked = [
            r[0] for r in db.fetchall("SELECT DISTINCT instrument_key FROM tracked_positions")
        ]
        return list(dict.fromkeys(market.watchlist_keys() + tracked))

    research = ResearchService(
        db, instruments, data, followed_keys, llm if settings.llm_rationales else None
    )
    lab = SignalLab(db, instruments, data)

    async def broker_holdings():
        return [parse_holding(r) for r in await provider.get_holdings_raw()]

    portfolio = PortfolioService(
        db,
        instruments,
        data,
        research,
        market.watchlist_keys,
        lab.verdicts,
        broker_holdings,
        lambda: auth.status().connected,
    )
    assistant = Assistant(db, portfolio, research, instruments, llm, monitor, budget, lab)
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
        market=market,
        news=NewsService(db, settings.news_enabled),
        research=research,
        portfolio=portfolio,
        assistant=assistant,
        tracker=TrackerService(db, instruments, data, portfolio, research, assistant.narrate),
        ipo=IpoService(db, instruments, candles, monitor),
        monitor=monitor,
        lab=lab,
        watcher=Watcher(db, instruments, quotes, research, portfolio, lab, monitor, followed_keys),
    )


async def _reference_data_loop(svc: Services) -> None:
    await svc.auth.verify(svc.provider)
    while True:
        await svc.instruments.refresh_if_needed()
        # Recovery after a restart: rebuild a missing or stale portfolio analysis.
        svc.portfolio.request_run()
        svc.lab.request_run()  # weekly: research validation replay
        try:
            removed = svc.db.cache_prune()
            if removed:
                logging.getLogger(__name__).info("pruned %d expired cache entries", removed)
        except Exception:  # housekeeping must never stop the loop
            logging.getLogger(__name__).exception("cache prune failed")
        await asyncio.sleep(REFERENCE_REFRESH_SECONDS)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    _configure_logging(settings.log_level)
    svc = build_services(settings)
    app.state.services = svc
    svc.hub.start()
    svc.research.start()
    svc.watcher.start()
    loader = asyncio.create_task(_reference_data_loop(svc))
    try:
        yield
    finally:
        loader.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await loader
        await svc.watcher.stop()
        await svc.lab.stop()
        await svc.portfolio.stop()
        await svc.research.stop()
        await svc.assistant.aclose()
        await svc.ipo.aclose()
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
    app.include_router(research.router)
    app.include_router(portfolio.router)
    app.include_router(assistant.router)
    app.include_router(events.router)
    app.include_router(tracker.router)
    app.include_router(ipo.router)
    app.include_router(ws.router)
    return app


app = create_app()
