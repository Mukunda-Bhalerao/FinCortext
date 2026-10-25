from dataclasses import dataclass

from fastapi import Request, WebSocket

from app.config import Settings
from app.db import Database
from app.providers.upstox import UpstoxProvider
from app.services.auth import AuthService
from app.services.candles import CandleService
from app.services.instruments import InstrumentService
from app.services.live import LiveHub
from app.services.market import MarketService
from app.services.news import NewsService
from app.services.quotes import QuoteService
from app.services.research import ResearchService
from app.services.session import SessionClock


@dataclass
class Services:
    settings: Settings
    db: Database
    provider: UpstoxProvider
    auth: AuthService
    clock: SessionClock
    hub: LiveHub
    instruments: InstrumentService
    quotes: QuoteService
    candles: CandleService
    market: MarketService
    news: NewsService
    research: ResearchService


def services(request: Request) -> Services:
    return request.app.state.services


def ws_services(websocket: WebSocket) -> Services:
    return websocket.app.state.services
