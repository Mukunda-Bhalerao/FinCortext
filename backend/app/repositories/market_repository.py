"""Repository for market price data (canonical layer)."""

from __future__ import annotations

from datetime import date

from app.data.storage.duckdb_storage import DuckDBStorage
from app.domain.models.market import MarketPrice


class MarketRepository:
    def __init__(self, storage: DuckDBStorage):
        self.storage = storage

    def upsert_bars(self, bars: list[MarketPrice]) -> int:
        """Insert/replace bars. Returns number of rows written."""
        if not bars:
            return 0
        rows = [
            (
                b.symbol,
                b.trade_date,
                b.open,
                b.high,
                b.low,
                b.close,
                b.volume,
                b.currency,
                b.provider_ticker,
                b.source_type.value,
                b.source_name,
                b.ingested_at,
            )
            for b in bars
        ]
        self.storage.execute("BEGIN TRANSACTION")
        try:
            self.storage.connect().executemany(
                """
                INSERT OR REPLACE INTO market_prices
                (symbol, trade_date, open, high, low, close, volume, currency,
                 provider_ticker, source_type, source_name, ingested_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
            self.storage.execute("COMMIT")
        except Exception:
            self.storage.execute("ROLLBACK")
            raise
        return len(rows)

    def get_prices(
        self,
        symbol: str,
        start: date | None = None,
        end: date | None = None,
    ) -> list[MarketPrice]:
        sql = "SELECT * FROM market_prices WHERE symbol = ?"
        params: list = [symbol.upper()]
        if start is not None:
            sql += " AND trade_date >= ?"
            params.append(start)
        if end is not None:
            sql += " AND trade_date <= ?"
            params.append(end)
        sql += " ORDER BY trade_date"
        rows = self.storage.fetch_all(sql, params)
        return [
            MarketPrice(
                symbol=r["symbol"],
                exchange="NSE",
                provider_ticker=r["provider_ticker"],
                trade_date=r["trade_date"],
                open=r["open"],
                high=r["high"],
                low=r["low"],
                close=r["close"],
                volume=r["volume"],
                currency=r["currency"],
                ingested_at=r["ingested_at"],
            )
            for r in rows
        ]

    def get_closes(self, symbol: str, start: date | None = None) -> list[tuple[date, float]]:
        """Convenience: ordered (date, close) pairs."""
        return [(p.trade_date, p.close) for p in self.get_prices(symbol, start)]

    def latest_trade_date(self, symbol: str) -> date | None:
        rows = self.storage.fetch_all(
            "SELECT MAX(trade_date) AS latest FROM market_prices WHERE symbol = ?",
            [symbol.upper()],
        )
        return rows[0]["latest"] if rows and rows[0]["latest"] else None

    def count(self, symbol: str | None = None) -> int:
        if symbol:
            rows = self.storage.fetch_all(
                "SELECT COUNT(*) AS n FROM market_prices WHERE symbol = ?",
                [symbol.upper()],
            )
        else:
            rows = self.storage.fetch_all("SELECT COUNT(*) AS n FROM market_prices")
        return int(rows[0]["n"]) if rows else 0