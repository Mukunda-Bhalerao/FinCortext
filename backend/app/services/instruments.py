"""Instrument master (from the provider) and index constituent lists, stored in DuckDB."""

import asyncio
import logging
from dataclasses import astuple
from datetime import UTC, datetime

from app.db import Database
from app.errors import NotFound
from app.providers import nse
from app.providers.base import MarketDataProvider
from app.schemas.market import Instrument
from app.tools.market_hours import to_ist

log = logging.getLogger(__name__)

# (label, segment, trading_symbol) — resolved against the instrument master at runtime.
HEADLINE_INDICES = [
    ("NIFTY 50", "NSE_INDEX", "NIFTY"),
    ("SENSEX", "BSE_INDEX", "SENSEX"),
    ("BANK NIFTY", "NSE_INDEX", "BANKNIFTY"),
    ("NIFTY IT", "NSE_INDEX", "NIFTY IT"),
    ("INDIA VIX", "NSE_INDEX", "INDIA VIX"),
]
SECTOR_INDICES = [
    ("Auto", "NIFTY AUTO"),
    ("Bank", "BANKNIFTY"),
    ("Financial Services", "FINNIFTY"),
    ("FMCG", "NIFTY FMCG"),
    ("Healthcare", "NIFTY HEALTHCARE"),
    ("IT", "NIFTY IT"),
    ("Media", "NIFTY MEDIA"),
    ("Metal", "NIFTY METAL"),
    ("Oil & Gas", "NIFTY OIL AND GAS"),
    ("Pharma", "NIFTY PHARMA"),
    ("PSU Bank", "NIFTY PSU BANK"),
    ("Private Bank", "NIFTY PVT BANK"),
    ("Realty", "NIFTY REALTY"),
    ("Energy", "NIFTY ENERGY"),
    ("Consumer Durables", "NIFTY CONSR DURBL"),
    ("Infrastructure", "NIFTY INFRA"),
]
MOVERS_UNIVERSE = "NIFTY 50"
INDUSTRY_UNIVERSE = "NIFTY 500"  # NSE industry classification and peer sets

_COLUMNS = (
    "instrument_key, trading_symbol, name, exchange, segment, instrument_type, isin, short_name"
)


def _row_to_instrument(row: tuple) -> Instrument:
    return Instrument(
        instrument_key=row[0],
        symbol=row[1],
        name=row[7] or row[2],
        exchange=row[3],
        segment=row[4],
        instrument_type=row[5],
        isin=row[6],
    )


class InstrumentService:
    def __init__(self, db: Database, provider: MarketDataProvider):
        self._db = db
        self._provider = provider
        self.ready = asyncio.Event()
        self.last_error: str | None = None
        if self.count() > 0:
            self.ready.set()

    def count(self) -> int:
        row = self._db.fetchone("SELECT count(*) FROM instruments")
        return int(row[0]) if row else 0

    def loaded_on(self) -> str | None:
        row = self._db.fetchone("SELECT v FROM meta WHERE k = 'instruments_loaded_on'")
        return row[0] if row else None

    async def refresh_if_needed(self) -> None:
        today = to_ist(datetime.now(UTC)).date().isoformat()
        if self.count() > 0 and self.loaded_on() == today:
            self.ready.set()
        else:
            try:
                records = await self._provider.fetch_instruments()
                await asyncio.to_thread(self._replace, records, today)
                log.info("instrument master loaded: %d instruments", len(records))
                self.last_error = None
            except Exception as exc:  # network or format failure; keep previous copy
                self.last_error = "Could not download the instrument master."
                log.warning("instrument master refresh failed: %s", exc)
            if self.count() > 0:
                self.ready.set()
        await self._refresh_constituents()

    def _replace(self, records: list, today: str) -> None:
        now = datetime.now(UTC)
        rows = [(*astuple(r), self._provider.name, now) for r in records]
        with self._db.cursor() as cur:
            cur.execute("BEGIN TRANSACTION")
            cur.execute("DELETE FROM instruments")
            cur.executemany(
                "INSERT OR REPLACE INTO instruments VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", rows
            )
            cur.execute(
                "INSERT OR REPLACE INTO meta VALUES ('instruments_loaded_on', ?, ?)", [today, now]
            )
            cur.execute("COMMIT")

    async def _refresh_constituents(self) -> None:
        for index_name in nse.CONSTITUENT_FILES:
            row = self._db.fetchone(
                "SELECT max(loaded_at) FROM index_constituents WHERE index_name = ?", [index_name]
            )
            if row and row[0] and (datetime.now(UTC) - row[0]).days < 7:
                continue
            try:
                members = await nse.fetch_constituents(index_name)
            except Exception as exc:
                log.warning("constituent refresh failed for %s: %s", index_name, exc)
                continue
            if members:
                self._store_constituents(index_name, members)

    def _store_constituents(self, index_name: str, members: list[nse.Constituent]) -> None:
        now = datetime.now(UTC)
        with self._db.cursor() as cur:
            cur.execute("BEGIN TRANSACTION")
            cur.execute("DELETE FROM index_constituents WHERE index_name = ?", [index_name])
            cur.executemany(
                "INSERT OR REPLACE INTO index_constituents VALUES (?,?,?,?,?,?,?)",
                [
                    (index_name, m.symbol, m.isin, m.company, m.industry, "nseindia.com", now)
                    for m in members
                ],
            )
            cur.execute("COMMIT")

    # --- lookups -----------------------------------------------------------------

    def search(self, query: str, limit: int = 20) -> list[Instrument]:
        q = query.strip().upper()
        if not q:
            return []
        rows = self._db.fetchall(
            f"""
            SELECT {_COLUMNS},
                CASE
                    WHEN upper(trading_symbol) = ? THEN 0
                    WHEN upper(trading_symbol) LIKE ? THEN 1
                    WHEN upper(coalesce(short_name, name)) LIKE ? THEN 2
                    ELSE 3
                END AS rank
            FROM instruments
            WHERE upper(trading_symbol) LIKE ? OR upper(name) LIKE ? OR upper(short_name) LIKE ?
                OR isin = ?
            ORDER BY rank, CASE instrument_type WHEN 'INDEX' THEN 0 WHEN 'EQ' THEN 1 ELSE 2 END,
                length(trading_symbol), trading_symbol
            LIMIT ?
            """,
            [q, f"{q}%", f"{q}%", f"%{q}%", f"%{q}%", f"%{q}%", q, limit],
        )
        return [_row_to_instrument(r) for r in rows]

    def get(self, instrument_key: str) -> Instrument:
        row = self._db.fetchone(
            f"SELECT {_COLUMNS} FROM instruments WHERE instrument_key = ?", [instrument_key]
        )
        if row is None:
            raise NotFound(f"Unknown instrument: {instrument_key}")
        return _row_to_instrument(row)

    def get_many(self, keys: list[str]) -> dict[str, Instrument]:
        if not keys:
            return {}
        rows = self._db.fetchall(
            f"SELECT {_COLUMNS} FROM instruments WHERE list_contains(?, instrument_key)", [keys]
        )
        return {r[0]: _row_to_instrument(r) for r in rows}

    def by_symbol(self, symbol: str, segment: str = "NSE_EQ") -> Instrument:
        row = self._db.fetchone(
            f"SELECT {_COLUMNS} FROM instruments WHERE segment = ? AND upper(trading_symbol) = ?",
            [segment, symbol.upper()],
        )
        if row is None:
            raise NotFound(f"No {segment} instrument with symbol {symbol}")
        return _row_to_instrument(row)

    def headline_indices(self) -> list[tuple[str, Instrument | None]]:
        out = []
        for label, segment, symbol in HEADLINE_INDICES:
            try:
                out.append((label, self.by_symbol(symbol, segment)))
            except NotFound:
                out.append((label, None))
        return out

    def sector_indices(self) -> list[tuple[str, Instrument]]:
        out = []
        for label, symbol in SECTOR_INDICES:
            try:
                out.append((label, self.by_symbol(symbol, "NSE_INDEX")))
            except NotFound:
                continue
        return out

    def constituents(self, index_name: str = MOVERS_UNIVERSE) -> list[Instrument]:
        rows = self._db.fetchall(
            f"""
            SELECT {", ".join("i." + c.strip() for c in _COLUMNS.split(","))}
            FROM index_constituents c
            JOIN instruments i ON i.isin = c.isin AND i.segment = 'NSE_EQ'
            WHERE c.index_name = ?
            ORDER BY i.trading_symbol
            """,
            [index_name],
        )
        return [_row_to_instrument(r) for r in rows]

    def industry_of(self, isin: str | None, index_name: str = INDUSTRY_UNIVERSE) -> str | None:
        """NSE industry classification for a member of the industry universe."""
        if not isin:
            return None
        row = self._db.fetchone(
            "SELECT industry FROM index_constituents WHERE index_name = ? AND isin = ?",
            [index_name, isin],
        )
        return row[0] if row else None

    def industry_members(
        self, industry: str, index_name: str = INDUSTRY_UNIVERSE
    ) -> list[Instrument]:
        rows = self._db.fetchall(
            f"""
            SELECT {", ".join("i." + c.strip() for c in _COLUMNS.split(","))}
            FROM index_constituents c
            JOIN instruments i ON i.isin = c.isin AND i.segment = 'NSE_EQ'
            WHERE c.index_name = ? AND c.industry = ?
            ORDER BY i.trading_symbol
            """,
            [index_name, industry],
        )
        return [_row_to_instrument(r) for r in rows]

    def constituents_expected(self, index_name: str = MOVERS_UNIVERSE) -> int:
        row = self._db.fetchone(
            "SELECT count(*) FROM index_constituents WHERE index_name = ?", [index_name]
        )
        return int(row[0]) if row else 0
