"""DuckDB connection, schema and a small provider-response cache."""

import json
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import duckdb

SCHEMA = """
CREATE TABLE IF NOT EXISTS auth_tokens (
    provider      VARCHAR PRIMARY KEY,
    access_token  VARCHAR NOT NULL,
    user_id       VARCHAR,
    user_name     VARCHAR,
    obtained_at   TIMESTAMPTZ NOT NULL,
    expires_at    TIMESTAMPTZ
);
CREATE TABLE IF NOT EXISTS provider_cache (
    cache_key   VARCHAR PRIMARY KEY,
    source      VARCHAR NOT NULL,
    payload     VARCHAR NOT NULL,
    fetched_at  TIMESTAMPTZ NOT NULL,
    expires_at  TIMESTAMPTZ NOT NULL
);
CREATE TABLE IF NOT EXISTS instruments (
    instrument_key   VARCHAR PRIMARY KEY,
    segment          VARCHAR NOT NULL,
    exchange         VARCHAR NOT NULL,
    instrument_type  VARCHAR NOT NULL,
    trading_symbol   VARCHAR NOT NULL,
    name             VARCHAR,
    short_name       VARCHAR,
    isin             VARCHAR,
    exchange_token   VARCHAR,
    lot_size         INTEGER,
    tick_size        DOUBLE,
    source           VARCHAR NOT NULL,
    loaded_at        TIMESTAMPTZ NOT NULL
);
CREATE TABLE IF NOT EXISTS index_constituents (
    index_name  VARCHAR NOT NULL,
    symbol      VARCHAR NOT NULL,
    isin        VARCHAR NOT NULL,
    company     VARCHAR,
    industry    VARCHAR,
    source      VARCHAR NOT NULL,
    loaded_at   TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (index_name, isin)
);
CREATE TABLE IF NOT EXISTS watchlist (
    instrument_key  VARCHAR PRIMARY KEY,
    added_at        TIMESTAMPTZ NOT NULL
);
CREATE TABLE IF NOT EXISTS meta (
    k           VARCHAR PRIMARY KEY,
    v           VARCHAR NOT NULL,
    updated_at  TIMESTAMPTZ NOT NULL
);
"""


class Database:
    """Single shared DuckDB connection guarded by a lock.

    Statements are short, so callers run them inline; bulk loads go through
    ``asyncio.to_thread`` at the call site.
    """

    def __init__(self, path: Path | str):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = duckdb.connect(str(path))
        self._lock = threading.RLock()
        with self.cursor() as cur:
            cur.execute(SCHEMA)

    @contextmanager
    def cursor(self) -> Iterator[duckdb.DuckDBPyConnection]:
        with self._lock:
            cur = self._conn.cursor()
            try:
                yield cur
            finally:
                cur.close()

    def fetchall(self, sql: str, params: list[Any] | None = None) -> list[tuple[Any, ...]]:
        with self.cursor() as cur:
            return cur.execute(sql, params or []).fetchall()

    def fetchone(self, sql: str, params: list[Any] | None = None) -> tuple[Any, ...] | None:
        with self.cursor() as cur:
            return cur.execute(sql, params or []).fetchone()

    def execute(self, sql: str, params: list[Any] | None = None) -> None:
        with self.cursor() as cur:
            cur.execute(sql, params or [])

    # --- provider response cache -------------------------------------------------

    def cache_get(self, key: str) -> tuple[Any, datetime] | None:
        """Return (payload, fetched_at) if an unexpired entry exists."""
        row = self.fetchone(
            "SELECT payload, fetched_at FROM provider_cache WHERE cache_key = ? AND expires_at > ?",
            [key, datetime.now(UTC)],
        )
        if row is None:
            return None
        return json.loads(row[0]), _as_utc(row[1])

    def cache_put(self, key: str, source: str, payload: Any, ttl: timedelta) -> datetime:
        now = datetime.now(UTC)
        self.execute(
            "INSERT OR REPLACE INTO provider_cache VALUES (?, ?, ?, ?, ?)",
            [key, source, json.dumps(payload), now, now + ttl],
        )
        return now

    def close(self) -> None:
        with self._lock:
            self._conn.close()


def _as_utc(value: datetime) -> datetime:
    return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
