"""Repository mirroring the versioned universe config into DuckDB."""

from __future__ import annotations

import time

from app.core.exceptions import StorageError
from app.core.logging import get_logger
from app.data.storage.duckdb_storage import DuckDBStorage
from app.data.universe.universe_config import (
    UNIVERSE_VERSION,
    get_static_universe,
    get_universe,
)
from app.domain.models.universe import UniverseEntry

logger = get_logger("repositories.universe")

# Substrings (case-insensitive) marking transient write conflicts worth one
# retry cycle: concurrent startup workers sharing one DuckDB file, or threads
# racing the first-ever sync.
_TRANSIENT_CONFLICT_MARKERS = ("conflict", "lock", "busy")

_SYNC_MAX_ATTEMPTS = 4
_SYNC_BACKOFF_SECONDS = (0.2, 0.5, 1.0)


class UniverseRepository:
    def __init__(self, storage: DuckDBStorage):
        self.storage = storage

    def sync_from_config(self) -> int:
        """Upsert the configured universe into the DB mirror.

        Startup-safe: when every static entry is already mirrored at the
        current version the call performs ZERO writes and returns 0, so
        repeat/concurrent startup workers can never conflict with each
        other. Otherwise a bounded retry absorbs genuine write races
        (transient ``Conflict on update`` / lock errors); anything else —
        and any exhausted retry — still raises instead of hiding the error.
        Dynamic entries are never touched here (see ``upsert_entry``).
        """
        try:
            mirrored = {
                r["symbol"]: r.get("universe_version")
                for r in self.storage.fetch_all(
                    "SELECT symbol, universe_version FROM universe_metadata"
                )
            }
        except Exception:
            mirrored = {}
        static_entries = get_static_universe()
        if static_entries and all(
            mirrored.get(e.symbol) == UNIVERSE_VERSION for e in static_entries
        ):
            return 0
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
        sql = """
            INSERT OR REPLACE INTO universe_metadata
            (symbol, name, exchange, ticker, sector, industry, universe_version, instrument_key)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """
        attempt = 0
        while True:
            try:
                self.storage.executemany(sql, rows)
                return len(rows)
            except StorageError as exc:
                attempt += 1
                message = str(exc).lower()
                transient = any(m in message for m in _TRANSIENT_CONFLICT_MARKERS)
                if not transient or attempt >= _SYNC_MAX_ATTEMPTS:
                    raise
                backoff = _SYNC_BACKOFF_SECONDS[min(attempt - 1, len(_SYNC_BACKOFF_SECONDS) - 1)]
                logger.warning(
                    "Universe sync conflict (attempt %d/%d); retrying in %.1fs",
                    attempt, _SYNC_MAX_ATTEMPTS, backoff,
                )
                time.sleep(backoff)

    def upsert_entry(self, entry: UniverseEntry) -> None:
        """Persist one (possibly dynamic) universe entry into the DB mirror."""
        self.storage.execute(
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