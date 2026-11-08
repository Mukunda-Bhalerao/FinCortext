"""DuckDB connection, schema and a small provider-response cache."""

import json
import logging
import shutil
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import duckdb

log = logging.getLogger(__name__)

BACKUPS_KEPT = 3
BACKUP_EVERY = timedelta(hours=20)

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
CREATE TABLE IF NOT EXISTS research_reports (
    instrument_key  VARCHAR PRIMARY KEY,
    signal          VARCHAR NOT NULL,
    payload         VARCHAR NOT NULL,
    computed_at     TIMESTAMPTZ NOT NULL
);
CREATE TABLE IF NOT EXISTS research_history (
    instrument_key  VARCHAR NOT NULL,
    computed_at     TIMESTAMPTZ NOT NULL,
    snapshot_date   DATE NOT NULL,  -- IST date; older days keep only their last run
    signal          VARCHAR NOT NULL,
    score           DOUBLE,
    confidence      DOUBLE NOT NULL,
    payload         VARCHAR NOT NULL,
    PRIMARY KEY (instrument_key, computed_at)
);
CREATE TABLE IF NOT EXISTS fundamentals_history (
    symbol        VARCHAR NOT NULL,
    observed_on   DATE NOT NULL,
    payload       VARCHAR NOT NULL,
    fetched_at    TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (symbol, observed_on)
);
CREATE TABLE IF NOT EXISTS dividends (
    symbol     VARCHAR NOT NULL,
    ex_date    DATE NOT NULL,
    amount     DOUBLE NOT NULL,
    source     VARCHAR NOT NULL,
    loaded_at  TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (symbol, ex_date)
);
CREATE TABLE IF NOT EXISTS statements (
    symbol      VARCHAR NOT NULL,
    item        VARCHAR NOT NULL,
    period_end  DATE NOT NULL,
    value       DOUBLE NOT NULL,
    source      VARCHAR NOT NULL,
    loaded_at   TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (symbol, item, period_end)
);
CREATE TABLE IF NOT EXISTS lab_runs (
    id           VARCHAR PRIMARY KEY,
    payload      VARCHAR NOT NULL,
    computed_at  TIMESTAMPTZ NOT NULL
);
CREATE TABLE IF NOT EXISTS forward_signals (
    snapshot_date  DATE NOT NULL,  -- signals recorded before their outcomes exist
    symbol         VARCHAR NOT NULL,
    signal_key     VARCHAR NOT NULL,
    score          DOUBLE NOT NULL,
    recorded_at    TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (snapshot_date, symbol, signal_key)
);
CREATE TABLE IF NOT EXISTS events (
    id          VARCHAR PRIMARY KEY,
    kind        VARCHAR NOT NULL,
    severity    VARCHAR NOT NULL,
    symbol      VARCHAR,
    title       VARCHAR NOT NULL,
    body        VARCHAR NOT NULL,
    facts       VARCHAR NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL,
    seen        BOOLEAN NOT NULL DEFAULT FALSE
);
ALTER TABLE events ADD COLUMN IF NOT EXISTS priority DOUBLE DEFAULT 0;
CREATE TABLE IF NOT EXISTS llm_usage (
    day         DATE NOT NULL,
    purpose     VARCHAR NOT NULL,
    calls       INTEGER NOT NULL,
    prompt_tokens  BIGINT NOT NULL,
    output_tokens  BIGINT NOT NULL,
    PRIMARY KEY (day, purpose)
);
CREATE TABLE IF NOT EXISTS tracked_portfolios (
    id              VARCHAR PRIMARY KEY,
    name            VARCHAR NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL,
    last_viewed_at  TIMESTAMPTZ
);
CREATE TABLE IF NOT EXISTS tracked_positions (
    id              VARCHAR PRIMARY KEY,
    portfolio_id    VARCHAR NOT NULL,
    instrument_key  VARCHAR NOT NULL,
    quantity        DOUBLE NOT NULL,
    entry_price     DOUBLE NOT NULL,
    entry_at        TIMESTAMPTZ NOT NULL,
    entry_basis     VARCHAR NOT NULL
);
ALTER TABLE tracked_portfolios ADD COLUMN IF NOT EXISTS kind VARCHAR DEFAULT 'tracking';
ALTER TABLE tracked_portfolios ADD COLUMN IF NOT EXISTS starting_cash DOUBLE;
ALTER TABLE tracked_portfolios ADD COLUMN IF NOT EXISTS cash DOUBLE;
ALTER TABLE tracked_portfolios ADD COLUMN IF NOT EXISTS plan VARCHAR DEFAULT 'zero';
ALTER TABLE tracked_positions ADD COLUMN IF NOT EXISTS charges DOUBLE DEFAULT 0;
ALTER TABLE tracked_positions ADD COLUMN IF NOT EXISTS reason VARCHAR;
ALTER TABLE tracked_positions ADD COLUMN IF NOT EXISTS tag VARCHAR;
ALTER TABLE tracked_positions ADD COLUMN IF NOT EXISTS index_at_entry DOUBLE;
ALTER TABLE tracked_positions ADD COLUMN IF NOT EXISTS order_id VARCHAR;
CREATE TABLE IF NOT EXISTS paper_orders (
    id              VARCHAR PRIMARY KEY,
    portfolio_id    VARCHAR NOT NULL,
    instrument_key  VARCHAR NOT NULL,
    side            VARCHAR NOT NULL,      -- BUY or SELL
    kind            VARCHAR NOT NULL,      -- MARKET, LIMIT or SL (stop-loss market)
    validity        VARCHAR NOT NULL,      -- DAY or GTC
    quantity        DOUBLE NOT NULL,
    limit_price     DOUBLE,
    trigger_price   DOUBLE,
    est_price       DOUBLE,                -- price used to set cash aside for a buy
    status          VARCHAR NOT NULL,      -- OPEN, FILLED, CANCELLED, EXPIRED, REJECTED
    created_at      TIMESTAMPTZ NOT NULL,
    session         DATE NOT NULL,         -- trading day a DAY order belongs to
    updated_at      TIMESTAMPTZ NOT NULL,
    fill_price      DOUBLE,
    filled_at       TIMESTAMPTZ,
    fill_basis      VARCHAR,
    charges         JSON,
    reason          VARCHAR,
    tag             VARCHAR,
    target_price    DOUBLE,                -- on a buy: sell order placed once it fills
    stop_price      DOUBLE,
    parent_id       VARCHAR,               -- exits created by a filled buy (one cancels other)
    source          VARCHAR NOT NULL,      -- 'you' or 'strategy:<id>'
    message         VARCHAR
);
CREATE TABLE IF NOT EXISTS paper_trades (
    id              VARCHAR PRIMARY KEY,
    portfolio_id    VARCHAR NOT NULL,
    instrument_key  VARCHAR NOT NULL,
    quantity        DOUBLE NOT NULL,
    buy_price       DOUBLE NOT NULL,
    buy_at          TIMESTAMPTZ NOT NULL,
    buy_charges     DOUBLE NOT NULL,
    sell_price      DOUBLE NOT NULL,
    sell_at         TIMESTAMPTZ NOT NULL,
    sell_charges    DOUBLE NOT NULL,
    buy_reason      VARCHAR,
    buy_tag         VARCHAR,
    sell_reason     VARCHAR,
    index_at_buy    DOUBLE,
    index_at_sell   DOUBLE,
    source          VARCHAR
);
CREATE TABLE IF NOT EXISTS strategies (
    id              VARCHAR PRIMARY KEY,
    name            VARCHAR NOT NULL,
    rules           JSON NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL,
    portfolio_id    VARCHAR,               -- paper account it trades forward in, if any
    symbols         JSON,
    per_trade       DOUBLE,
    active          BOOLEAN DEFAULT FALSE,
    last_run        DATE,
    last_note       VARCHAR
);
CREATE TABLE IF NOT EXISTS ipo_history (
    symbol          VARCHAR PRIMARY KEY,
    company         VARCHAR NOT NULL,
    board           VARCHAR NOT NULL,
    isin            VARCHAR,
    issue_price     DOUBLE,
    listing_date    DATE,
    qib             DOUBLE,
    total           DOUBLE,
    subscription    JSON,
    listing_open    DOUBLE,
    listing_close   DOUBLE,
    fetched_at      TIMESTAMPTZ NOT NULL
);
CREATE TABLE IF NOT EXISTS holdings (
    instrument_key  VARCHAR PRIMARY KEY,
    quantity        DOUBLE NOT NULL,
    avg_cost        DOUBLE,
    updated_at      TIMESTAMPTZ NOT NULL
);
ALTER TABLE holdings ADD COLUMN IF NOT EXISTS source VARCHAR DEFAULT 'manual';
ALTER TABLE holdings ADD COLUMN IF NOT EXISTS broker_pnl DOUBLE;
CREATE TABLE IF NOT EXISTS text_cache (
    k           VARCHAR PRIMARY KEY,
    model       VARCHAR NOT NULL,
    text        VARCHAR NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL
);
CREATE TABLE IF NOT EXISTS portfolio_runs (
    id           VARCHAR PRIMARY KEY,
    signature    VARCHAR NOT NULL,
    payload      VARCHAR NOT NULL,
    computed_at  TIMESTAMPTZ NOT NULL
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
        self.path = None if str(path) == ":memory:" else Path(path)
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            backup(self.path)
        self._conn = _connect(self.path)
        self._lock = threading.RLock()
        with self.cursor() as cur:
            cur.execute(SCHEMA)

    def size_bytes(self) -> int | None:
        return self.path.stat().st_size if self.path and self.path.exists() else None

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

    def cache_prune(self) -> int:
        """Drop cache entries that expired more than a day ago; returns rows removed."""
        cutoff = datetime.now(UTC) - timedelta(days=1)
        row = self.fetchone("SELECT count(*) FROM provider_cache WHERE expires_at < ?", [cutoff])
        self.execute("DELETE FROM provider_cache WHERE expires_at < ?", [cutoff])
        return int(row[0]) if row else 0

    def close(self) -> None:
        with self._lock:
            self._conn.close()


def _backups(path: Path) -> list[Path]:
    folder = path.parent / "backups"
    return sorted(folder.glob(f"{path.stem}-*{path.suffix}")) if folder.exists() else []


def backup(path: Path) -> Path | None:
    """Copy the database file before it is opened, at most once per BACKUP_EVERY.

    Run at startup only, while no connection holds the file, so the copy is consistent.
    """
    if not path.exists():
        return None
    existing = _backups(path)
    if existing:
        newest = datetime.fromtimestamp(existing[-1].stat().st_mtime, UTC)
        if datetime.now(UTC) - newest < BACKUP_EVERY:
            return None
    target = path.parent / "backups" / f"{path.stem}-{datetime.now(UTC):%Y%m%d-%H%M%S}{path.suffix}"
    target.parent.mkdir(parents=True, exist_ok=True)
    wal = path.with_name(path.name + ".wal")
    try:
        shutil.copy2(path, target)
        if wal.exists():  # un-checkpointed changes after an unclean shutdown
            shutil.copy2(wal, target.with_name(target.name + ".wal"))
    except OSError as exc:  # another process holds the file; skip rather than fail startup
        log.warning("database backup skipped: %s", exc)
        return None
    for old in _backups(path)[:-BACKUPS_KEPT]:
        old.unlink(missing_ok=True)
        old.with_name(old.name + ".wal").unlink(missing_ok=True)
    return target


_LOCKED = ("lock", "already open", "being used")


def _connect(path: Path | None) -> duckdb.DuckDBPyConnection:
    """Open the database; if the file is unreadable, set it aside and restore the newest backup."""
    if path is None:
        return duckdb.connect(":memory:")
    try:
        return duckdb.connect(str(path))
    except duckdb.Error as exc:
        if any(m in str(exc).lower() for m in _LOCKED) or not path.exists():
            raise
        aside = path.with_suffix(f".unreadable-{datetime.now(UTC):%Y%m%d-%H%M%S}")
        path.rename(aside)
        stale_wal = path.with_name(path.name + ".wal")
        if stale_wal.exists():
            stale_wal.rename(aside.with_name(aside.name + ".wal"))
        restored = _backups(path)
        if restored:
            shutil.copy2(restored[-1], path)
            wal = restored[-1].with_name(restored[-1].name + ".wal")
            if wal.exists():
                shutil.copy2(wal, path.with_name(path.name + ".wal"))
            log.error(
                "database unreadable (%s); moved to %s and restored %s", exc, aside, restored[-1]
            )
        else:
            log.error("database unreadable (%s); moved to %s and started empty", exc, aside)
        return duckdb.connect(str(path))


def _as_utc(value: datetime) -> datetime:
    return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
