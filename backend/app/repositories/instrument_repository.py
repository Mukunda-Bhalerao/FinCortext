"""Repository caching Upstox instrument metadata (dynamic NSE equities).

Persists the instrument_key-centred metadata resolved via Upstox search so a
valid NSE equity selected once stays resolvable across restarts without
re-searching. Never stores secrets.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.data.storage.duckdb_storage import DuckDBStorage


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class InstrumentRepository:
    def __init__(self, storage: DuckDBStorage):
        self.storage = storage

    def upsert(self, meta: dict) -> None:
        key = str(meta.get("instrument_key") or "").strip()
        if not key:
            return
        symbol = str(meta.get("symbol") or meta.get("trading_symbol") or "").strip().upper()
        self.storage.connect().execute(
            """
            INSERT OR REPLACE INTO upstox_instruments
            (instrument_key, symbol, trading_symbol, name, exchange, segment,
             isin, exchange_token, instrument_type, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                key,
                symbol,
                str(meta.get("trading_symbol") or symbol),
                str(meta.get("name") or symbol),
                str(meta.get("exchange") or "NSE"),
                str(meta.get("segment") or "EQ"),
                meta.get("isin"),
                meta.get("exchange_token"),
                meta.get("instrument_type"),
                _utcnow(),
            ],
        )

    def get_by_symbol(self, symbol: str) -> dict | None:
        rows = self.storage.fetch_all(
            "SELECT * FROM upstox_instruments WHERE symbol = ? ORDER BY updated_at DESC LIMIT 1",
            [(symbol or "").strip().upper()],
        )
        return dict(rows[0]) if rows else None

    def get_by_key(self, instrument_key: str) -> dict | None:
        rows = self.storage.fetch_all(
            "SELECT * FROM upstox_instruments WHERE instrument_key = ?",
            [(instrument_key or "").strip()],
        )
        return dict(rows[0]) if rows else None

    def list_all(self, limit: int = 500) -> list[dict]:
        rows = self.storage.fetch_all(
            "SELECT * FROM upstox_instruments ORDER BY symbol LIMIT ?",
            [max(1, int(limit or 500))],
        )
        return [dict(r) for r in rows]
