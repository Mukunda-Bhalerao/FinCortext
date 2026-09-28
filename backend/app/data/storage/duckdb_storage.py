"""DuckDB storage: connection management and schema initialization.

Single local analytical database. Raw/source concepts (filing documents,
provenance) are stored separately from normalized canonical data
(market prices, financial observations, news articles, agent outputs).
"""

from __future__ import annotations

from pathlib import Path
from threading import RLock

import duckdb

from app.core.config import Settings, settings
from app.core.exceptions import StorageError
from app.core.logging import get_logger

logger = get_logger("storage.duckdb")

SCHEMA_VERSION = 1

_SCHEMA_STATEMENTS = [
    # --- Universe metadata (mirror of the versioned config) -------------
    """
    CREATE TABLE IF NOT EXISTS universe_metadata (
        symbol VARCHAR PRIMARY KEY,
        name VARCHAR,
        exchange VARCHAR,
        ticker VARCHAR,
        sector VARCHAR,
        industry VARCHAR,
        universe_version VARCHAR
    )
    """,
    # --- Market prices (normalized canonical) ---------------------------
    """
    CREATE TABLE IF NOT EXISTS market_prices (
        symbol VARCHAR,
        trade_date DATE,
        open DOUBLE,
        high DOUBLE,
        low DOUBLE,
        close DOUBLE,
        volume DOUBLE,
        currency VARCHAR,
        provider_ticker VARCHAR,
        source_type VARCHAR,
        source_name VARCHAR,
        ingested_at TIMESTAMP,
        PRIMARY KEY (symbol, trade_date)
    )
    """,
    # --- Financial observations (normalized canonical) ------------------
    """
    CREATE TABLE IF NOT EXISTS financial_observations (
        observation_id VARCHAR PRIMARY KEY,
        entity_id VARCHAR,
        metric VARCHAR,
        value DOUBLE,
        unit VARCHAR,
        currency VARCHAR,
        period_start DATE,
        period_end DATE,
        statement_type VARCHAR,
        consolidation_basis VARCHAR,
        fiscal_year VARCHAR,
        source_type VARCHAR,
        source_name VARCHAR,
        source_reference VARCHAR,
        raw_document_reference VARCHAR,
        content_hash VARCHAR,
        filing_date TIMESTAMP,
        published_at TIMESTAMP,
        available_at TIMESTAMP,
        schema_version VARCHAR,
        ingested_at TIMESTAMP
    )
    """,
    # --- Filing documents (raw layer metadata) --------------------------
    """
    CREATE TABLE IF NOT EXISTS filing_documents (
        document_id VARCHAR PRIMARY KEY,
        entity_id VARCHAR,
        document_type VARCHAR,
        file_name VARCHAR,
        file_path VARCHAR,
        content_hash VARCHAR,
        source_type VARCHAR,
        source_name VARCHAR,
        source_url VARCHAR,
        filing_date TIMESTAMP,
        published_at TIMESTAMP,
        ingested_at TIMESTAMP,
        observation_count INTEGER,
        parse_warnings VARCHAR
    )
    """,
    # --- News articles (normalized canonical) ---------------------------
    """
    CREATE TABLE IF NOT EXISTS news_articles (
        article_id VARCHAR PRIMARY KEY,
        entity_id VARCHAR,
        title VARCHAR,
        description VARCHAR,
        content VARCHAR,
        source VARCHAR,
        source_url VARCHAR,
        published_at TIMESTAMP,
        collected_at TIMESTAMP,
        language VARCHAR,
        content_hash VARCHAR,
        source_type VARCHAR,
        source_name VARCHAR
    )
    """,
    # --- Sentiment results ----------------------------------------------
    """
    CREATE TABLE IF NOT EXISTS sentiment_results (
        article_id VARCHAR,
        entity_id VARCHAR,
        label VARCHAR,
        positive_probability DOUBLE,
        neutral_probability DOUBLE,
        negative_probability DOUBLE,
        model_id VARCHAR,
        model_confidence DOUBLE,
        scored_at TIMESTAMP,
        PRIMARY KEY (article_id, model_id)
    )
    """,
    # --- Agent outputs (standardized contract persistence) --------------
    """
    CREATE TABLE IF NOT EXISTS agent_outputs (
        output_id VARCHAR,
        agent_id VARCHAR,
        entity_id VARCHAR,
        score DOUBLE,
        signal VARCHAR,
        confidence DOUBLE,
        factors_json VARCHAR,
        rationale VARCHAR,
        generated_at TIMESTAMP,
        data_version VARCHAR,
        status VARCHAR,
        PRIMARY KEY (output_id)
    )
    """,
    # --- Data provenance / ingestion events ------------------------------
    """
    CREATE TABLE IF NOT EXISTS data_provenance (
        event_id VARCHAR,
        event_type VARCHAR,
        entity_id VARCHAR,
        source_type VARCHAR,
        source_name VARCHAR,
        content_hash VARCHAR,
        rows_ingested INTEGER,
        rows_rejected INTEGER,
        detail VARCHAR,
        ingested_at TIMESTAMP,
        PRIMARY KEY (event_id)
    )
    """,
    # --- Macro observations (market-wide, point-in-time aware) ----------
    """
    CREATE TABLE IF NOT EXISTS macro_observations (
        observation_id VARCHAR,
        indicator_id VARCHAR,
        value DOUBLE,
        unit VARCHAR,
        period_start DATE,
        period_end DATE,
        observed_at DATE,
        published_at TIMESTAMP,
        available_at TIMESTAMP,
        source_type VARCHAR,
        source_name VARCHAR,
        source_url VARCHAR,
        content_hash VARCHAR,
        notes VARCHAR,
        ingested_at TIMESTAMP,
        PRIMARY KEY (observation_id)
    )
    """,
    # --- Macro outputs (market-wide environment views) ------------------
    """
    CREATE TABLE IF NOT EXISTS macro_outputs (
        output_id VARCHAR,
        generated_at TIMESTAMP,
        overall_signal VARCHAR,
        confidence DOUBLE,
        status VARCHAR,
        score DOUBLE,
        factors_json VARCHAR,
        rationale VARCHAR,
        data_through_json VARCHAR,
        limitations_json VARCHAR,
        methodology VARCHAR,
        PRIMARY KEY (output_id)
    )
    """,
    # --- Portfolio outputs (per-company synthesis views) ------------------
    """
    CREATE TABLE IF NOT EXISTS portfolio_outputs (
        output_id VARCHAR,
        entity_id VARCHAR,
        generated_at TIMESTAMP,
        view_json VARCHAR,
        status VARCHAR,
        PRIMARY KEY (output_id)
    )
    """,
    # --- Upstox instrument registry (dynamic NSE equity metadata cache) ----
    """
    CREATE TABLE IF NOT EXISTS upstox_instruments (
        instrument_key VARCHAR PRIMARY KEY,
        symbol VARCHAR,
        trading_symbol VARCHAR,
        name VARCHAR,
        exchange VARCHAR,
        segment VARCHAR,
        isin VARCHAR,
        exchange_token VARCHAR,
        instrument_type VARCHAR,
        updated_at TIMESTAMP
    )
    """,
]


class DuckDBStorage:
    """Thread-safe DuckDB connection wrapper with schema management."""

    def __init__(self, db_path: Path | str | None = None, *, read_only: bool = False):
        if db_path is None:
            db_path = settings.db_path
        self.db_path = Path(db_path)
        self._lock = RLock()
        self._read_only = read_only
        self._conn: duckdb.DuckDBPyConnection | None = None

    # -- lifecycle ---------------------------------------------------------

    def connect(self) -> duckdb.DuckDBPyConnection:
        with self._lock:
            if self._conn is None:
                try:
                    if not self._read_only:
                        self.db_path.parent.mkdir(parents=True, exist_ok=True)
                    self._conn = duckdb.connect(str(self.db_path), read_only=self._read_only)
                    if not self._read_only:
                        self._init_schema(self._conn)
                except duckdb.Error as exc:
                    raise StorageError(f"Failed to open DuckDB at {self.db_path}: {exc}") from exc
            return self._conn

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    def __enter__(self) -> "DuckDBStorage":
        self.connect()
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # -- query helpers -------------------------------------------------------

    def execute(self, sql: str, params: list | None = None) -> None:
        conn = self.connect()
        with self._lock:
            try:
                conn.execute(sql, params or [])
            except duckdb.Error as exc:
                raise StorageError(f"SQL failed: {exc}") from exc

    def fetch_all(self, sql: str, params: list | None = None) -> list[dict]:
        conn = self.connect()
        with self._lock:
            try:
                conn.execute(sql, params or [])
                columns = [d[0] for d in conn.description]
                rows = conn.fetchall()
            except duckdb.Error as exc:
                raise StorageError(f"SQL failed: {exc}") from exc
        return [dict(zip(columns, row)) for row in rows]

    def fetch_df(self, sql: str, params: list | None = None):
        import pandas as pd

        conn = self.connect()
        with self._lock:
            try:
                return conn.execute(sql, params or []).df()
            except duckdb.Error as exc:
                raise StorageError(f"SQL failed: {exc}") from exc

    # -- schema ----------------------------------------------------------------

    def _init_schema(self, conn: duckdb.DuckDBPyConnection) -> None:
        for statement in _SCHEMA_STATEMENTS:
            conn.execute(statement)
        # Additive migration for databases created before the macro score
        # column existed. Guarded so old and new databases both open cleanly;
        # the score is also embedded in factors_json, so nothing is lost
        # even if the migration cannot run.
        try:
            conn.execute("ALTER TABLE macro_outputs ADD COLUMN IF NOT EXISTS score DOUBLE")
        except duckdb.Error as exc:
            logger.debug("Macro score column migration skipped: %s", exc)
        # Additive migration: universe entries resolved dynamically via Upstox
        # carry their canonical instrument_key alongside the yfinance ticker.
        try:
            conn.execute("ALTER TABLE universe_metadata ADD COLUMN IF NOT EXISTS instrument_key VARCHAR")
        except duckdb.Error as exc:
            logger.debug("Universe instrument_key migration skipped: %s", exc)
        logger.debug("DuckDB schema ensured at %s (v%s)", self.db_path, SCHEMA_VERSION)


# Default shared instance for the running app (tests create their own).
_default_storage: DuckDBStorage | None = None
_storage_lock = RLock()


def get_storage() -> DuckDBStorage:
    """Return the app-wide storage singleton (lazily connected)."""
    global _default_storage
    with _storage_lock:
        if _default_storage is None:
            _default_storage = DuckDBStorage(settings.db_path)
        return _default_storage