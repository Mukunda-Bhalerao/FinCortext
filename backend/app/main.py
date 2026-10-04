"""FinCortext backend application entry point.

FastAPI application factory. Route modules are registered by domain.
Business logic lives in services/agents/repositories — never in route
handlers.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.core.exceptions import FinCortextError
from app.core.logging import configure_logging, get_logger

configure_logging(settings.log_level)
logger = get_logger("main")

APP_VERSION = "0.1.0"


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("FinCortext backend starting (version %s)", APP_VERSION)
    logger.info("Configuration: %s", settings.summary())
    yield
    logger.info("FinCortext backend shutting down")


def create_app() -> FastAPI:
    app = FastAPI(
        title="FinCortext API",
        description=(
            "AI-Powered Investment Intelligence and Agentic Portfolio "
            "Management Platform — backend API."
        ),
        version=APP_VERSION,
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # --- Domain error handling -----------------------------------------
    @app.exception_handler(FinCortextError)
    async def fincortext_error_handler(_: Request, exc: FinCortextError) -> JSONResponse:
        logger.warning("Domain error [%s]: %s", exc.code, exc.message)
        return JSONResponse(status_code=exc.http_status, content={"error": exc.to_dict()})

    @app.exception_handler(Exception)
    async def unhandled_error_handler(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled server error: %s", exc)
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "internal_error",
                    "message": "An unexpected internal error occurred.",
                    "details": {},
                }
            },
        )

    # --- Routes ----------------------------------------------------------
    from app.api.routes.health import router as health_router
    from app.api.routes.universe import router as universe_router
    from app.api.routes.market import router as market_router
    from app.api.routes.filings import router as filings_router
    from app.api.routes.fundamentals import router as fundamentals_router
    from app.api.routes.macro import router as macro_router
    from app.api.routes.portfolio import router as portfolio_router
    from app.api.routes.agents import router as agents_router
    from app.api.routes.news import router as news_router
    from app.api.routes.research import router as research_router
    from app.api.routes.stock import router as stock_router

    app.include_router(health_router)
    app.include_router(universe_router)
    app.include_router(market_router)
    app.include_router(filings_router)
    app.include_router(fundamentals_router)
    app.include_router(macro_router)
    app.include_router(portfolio_router)
    app.include_router(agents_router)
    app.include_router(news_router)
    app.include_router(research_router)
    app.include_router(stock_router)

    return app


app = create_app()