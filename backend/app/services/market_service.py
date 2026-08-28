"""Market data service: provider → validation → storage → provenance.

Orchestration layer used by API routes. Business logic lives here, not in
route handlers.
"""

from __future__ import annotations

from datetime import date, timedelta

from app.core.config import settings
from app.core.exceptions import ProviderError
from app.core.logging import get_logger
from app.data.universe.universe_config import get_universe, get_universe_entry
from app.data.validation.market_validation import validate_market_bars
from app.domain.contracts.providers import MarketDataProvider
from app.domain.models.base import DataStatus
from app.domain.models.market import MarketPrice
from app.repositories.market_repository import MarketRepository
from app.repositories.provenance_repository import ProvenanceRepository

logger = get_logger("services.market")


class MarketService:
    def __init__(
        self,
        provider: MarketDataProvider,
        market_repo: MarketRepository,
        provenance_repo: ProvenanceRepository,
    ):
        self.provider = provider
        self.market_repo = market_repo
        self.provenance_repo = provenance_repo

    def refresh_symbol(
        self,
        symbol: str,
        start: date | None = None,
        end: date | None = None,
    ) -> dict:
        """Fetch, validate, and store OHLCV for one universe symbol."""
        entry = get_universe_entry(symbol)
        end = end or date.today()
        start = start or (end - timedelta(days=settings.market_history_days))

        bars = self.provider.fetch_ohlcv(entry.ticker, start, end)
        validation = validate_market_bars(bars)

        written = 0
        if validation.valid:
            written = self.market_repo.upsert_bars(validation.valid)

        self.provenance_repo.record(
            "market_refresh",
            entity_id=entry.symbol,
            source_type=self.provider.name,
            source_name=self.provider.name,
            rows_ingested=written,
            rows_rejected=len(validation.rejected),
            detail=str(validation.summary()["rejections"]) if validation.rejected else None,
        )
        logger.info(
            "Market refresh %s: %d stored, %d rejected",
            entry.symbol, written, len(validation.rejected),
        )
        return {
            "symbol": entry.symbol,
            "status": DataStatus.LIVE.value if written else DataStatus.UNAVAILABLE.value,
            "rows_stored": written,
            "rows_rejected": len(validation.rejected),
            "provider": self.provider.name,
            "start": start.isoformat(),
            "end": end.isoformat(),
        }

    def refresh_universe(self, symbols: list[str] | None = None) -> dict:
        """Refresh all (or selected) universe symbols; failures are isolated."""
        entries = get_universe()
        results = []
        for entry in entries:
            if symbols and entry.symbol not in {s.upper() for s in symbols}:
                continue
            try:
                results.append(self.refresh_symbol(entry.symbol))
            except ProviderError as exc:
                logger.error("Market refresh failed for %s: %s", entry.symbol, exc.message)
                results.append(
                    {
                        "symbol": entry.symbol,
                        "status": DataStatus.ERROR.value,
                        "error": exc.message,
                    }
                )
        stored = sum(1 for r in results if r.get("status") == DataStatus.LIVE.value)
        return {
            "provider": self.provider.name,
            "symbols_requested": len(results),
            "symbols_ok": stored,
            "results": results,
        }

    def get_price_series(self, symbol: str, start: date | None = None, end: date | None = None) -> dict:
        """Stored price series with explicit data status."""
        entry = get_universe_entry(symbol)
        prices: list[MarketPrice] = self.market_repo.get_prices(entry.symbol, start, end)
        if not prices:
            status = DataStatus.UNAVAILABLE.value
        elif self.market_repo.latest_trade_date(entry.symbol) and (
            date.today() - self.market_repo.latest_trade_date(entry.symbol)
        ).days <= 7:
            status = DataStatus.LIVE.value
        else:
            status = DataStatus.CACHED.value
        return {
            "symbol": entry.symbol,
            "name": entry.name,
            "status": status,
            "count": len(prices),
            "latest_trade_date": (
                prices[-1].trade_date.isoformat() if prices else None
            ),
            "prices": [
                {
                    "date": p.trade_date.isoformat(),
                    "open": p.open,
                    "high": p.high,
                    "low": p.low,
                    "close": p.close,
                    "volume": p.volume,
                }
                for p in prices
            ],
        }