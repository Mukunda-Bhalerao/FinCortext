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
        rows = [
            (
                e.symbol,
                e.name,
                e.exchange,
                e.ticker,
                e.sector,
                e.industry,
                UNIVERSE_VERSION,
                getattr(e, "instrument_key", None),
            )
            for e in entries
        ]
        self.storage.connect().executemany(
            """
            INSERT OR REPLACE INTO universe_metadata
            (symbol, name, exchange, ticker, sector, industry, universe_version, instrument_key)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        return len(rows)

    def upsert_entry(self, entry: UniverseEntry) -> None:
        """Persist one (possibly dynamic) universe entry into the DB mirror."""
        self.storage.connect().execute(
            """
            INSERT OR REPLACE INTO universe_metadata
            (symbol, name, exchange, ticker, sector, industry, universe_version, instrument_key)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                entry.symbol,
                entry.name,
                entry.exchange,
                entry.ticker,
                entry.sector,
                entry.industry,
                UNIVERSE_VERSION,
                getattr(entry, "instrument_key", None),
            ],
        )

    def load_dynamic_entries(self) -> list[UniverseEntry]:
        """Load persisted dynamic entries (sector/industry Unknown) for startup hydration."""
        from app.data.universe.universe_config import _BY_SYMBOL as _STATIC

        rows = self.storage.fetch_all("SELECT * FROM universe_metadata ORDER BY symbol")
        out: list[UniverseEntry] = []
        for r in rows:
            sym = str(r.get("symbol") or "").upper()
            if not sym or sym in _STATIC:
                continue
            try:
                out.append(
                    UniverseEntry(
                        symbol=sym,
                        name=r.get("name") or sym,
                        exchange=r.get("exchange") or "NSE",
                        ticker=r.get("ticker") or f"{sym}.NS",
                        sector=r.get("sector") or "Unknown",
                        industry=r.get("industry") or "Unknown",
                        instrument_key=r.get("instrument_key"),
                    )
                )
            except Exception:
                continue
        return out

    def list_entries(self) -> list[UniverseEntry]:
        rows = self.storage.fetch_all("SELECT * FROM universe_metadata ORDER BY symbol")
        entries: list[UniverseEntry] = []
        for r in rows:
            try:
                entries.append(
                    UniverseEntry(
                        symbol=r["symbol"],
                        name=r["name"],
                        exchange=r["exchange"],
                        ticker=r["ticker"],
                        sector=r["sector"],
                        industry=r["industry"],
                        instrument_key=r.get("instrument_key"),
                    )
                )
            except Exception:
                continue
        return entries

    def get_entry(self, symbol: str) -> UniverseEntry | None:
        rows = self.storage.fetch_all(
            "SELECT * FROM universe_metadata WHERE symbol = ?", [symbol.upper()]
        )
        if not rows:
            return None
        r = rows[0]
        try:
            return UniverseEntry(
                symbol=r["symbol"],
                name=r["name"],
                exchange=r["exchange"],
                ticker=r["ticker"],
                sector=r["sector"],
                industry=r["industry"],
                instrument_key=r.get("instrument_key"),
            )
        except Exception:
            return None