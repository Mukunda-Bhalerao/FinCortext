"""Repository mirroring the versioned universe config into DuckDB."""

from __future__ import annotations

from app.data.storage.duckdb_storage import DuckDBStorage
from app.data.universe.universe_config import UNIVERSE_VERSION, get_universe
from app.domain.models.universe import UniverseEntry


class UniverseRepository:
    def __init__(self, storage: DuckDBStorage):
        self.storage = storage

    def sync_from_config(self) -> int:
        """Upsert the configured universe into the DB mirror."""
        entries = get_universe()
        rows = [(e.symbol, e.name, e.exchange, e.ticker, e.sector, e.industry, UNIVERSE_VERSION) for e in entries]
        self.storage.connect().executemany(
            """
            INSERT OR REPLACE INTO universe_metadata
            (symbol, name, exchange, ticker, sector, industry, universe_version)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        return len(rows)

    def list_entries(self) -> list[UniverseEntry]:
        rows = self.storage.fetch_all("SELECT * FROM universe_metadata ORDER BY symbol")
        return [
            UniverseEntry(
                symbol=r["symbol"],
                name=r["name"],
                exchange=r["exchange"],
                ticker=r["ticker"],
                sector=r["sector"],
                industry=r["industry"],
            )
            for r in rows
        ]

    def get_entry(self, symbol: str) -> UniverseEntry | None:
        rows = self.storage.fetch_all(
            "SELECT * FROM universe_metadata WHERE symbol = ?", [symbol.upper()]
        )
        if not rows:
            return None
        r = rows[0]
        return UniverseEntry(
            symbol=r["symbol"],
            name=r["name"],
            exchange=r["exchange"],
            ticker=r["ticker"],
            sector=r["sector"],
            industry=r["industry"],
        )