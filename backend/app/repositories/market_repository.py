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
        # Locked transaction: concurrent requests share one connection, so the
        # BEGIN..COMMIT sequence must be atomic (else "Conflict on update!").
        with self.storage.transaction() as conn:
            conn.executemany(
                """
                INSERT OR REPLACE INTO market_prices
                (symbol, trade_date, open, high, low, close, volume, currency,
                 provider_ticker, source_type, source_name, ingested_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
        return len(rows)

    def normalize_symbol_keys(self, ticker_to_symbol: dict[str, str]) -> int:
        """Re-key rows stored under provider tickers to canonical internal symbols.

        Repair for rows written before the canonical-key invariant was
        enforced (the provider ticker was mistakenly stored in the `symbol`
        column, e.g. 'TCS.NS'), which made every read by internal symbol
        return zero rows. Real price data is preserved:

        - rows whose trade_date is not already present under the internal
          symbol are re-keyed to it;
        - leftover rows under the provider ticker are exact
          (symbol, trade_date) duplicates of canonical rows and are removed.

        Idempotent: a second call with the same mapping is a no-op. Returns
        the number of rows re-keyed (dedup-removed rows are not counted).
        """
        rekeyed = 0
        for provider_ticker, symbol in ticker_to_symbol.items():
            provider_key = provider_ticker.upper()
            canonical = symbol.upper()
            if provider_key == canonical:
                continue
            rows = self.storage.fetch_all(
                "SELECT COUNT(*) AS n FROM market_prices WHERE symbol = ?",
                [provider_key],
            )
            stale = int(rows[0]["n"]) if rows else 0
            if not stale:
                continue
            dup_rows = self.storage.fetch_all(
                """
                SELECT COUNT(*) AS n FROM market_prices p
                WHERE p.symbol = ? AND EXISTS (
                    SELECT 1 FROM market_prices q
                    WHERE q.symbol = ? AND q.trade_date = p.trade_date
                )
                """,
                [provider_key, canonical],
            )
            duplicates = int(dup_rows[0]["n"]) if dup_rows else 0
            with self.storage.transaction() as conn:
                conn.execute(
                    """
                    UPDATE market_prices SET symbol = ?
                    WHERE symbol = ?
                      AND trade_date NOT IN (
                          SELECT trade_date FROM market_prices WHERE symbol = ?
                      )
                    """,
                    [canonical, provider_key, canonical],
                )
                conn.execute(
                    "DELETE FROM market_prices WHERE symbol = ?",
                    [provider_key],
                )
            rekeyed += stale - duplicates
        return rekeyed

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

    # -- live quote snapshots -------------------------------------------------

    @staticmethod
    def _quote_source_rank(source: str | None) -> int:
        """Upstox (primary) outranks yfinance fallback; unknown lowest."""
        s = (source or "").strip().lower()
        if s == "upstox":
            return 2
        if s == "yfinance":
            return 1
        return 0

    @staticmethod
    def _quote_ts_key(timestamp: str | None) -> str:
        """Comparable key for quote timestamps (ISO strings compare chronologically)."""
        return (timestamp or "").strip()

    def get_stored_quote(self, symbol: str) -> dict | None:
        """Latest stored quote snapshot for one symbol (None when absent)."""
        rows = self.storage.fetch_all(
            "SELECT * FROM market_quotes WHERE symbol = ?",
            [symbol.upper()],
        )
        return dict(rows[0]) if rows else None

    def upsert_quote(self, quote: dict) -> bool:
        """Store a quote snapshot; never let older data overwrite newer data.

        Rules (all comparisons on the provider timestamp, not wall clock):
        - a higher-ranked source (Upstox > yfinance) always wins;
        - within the same source rank, the newer timestamp wins;
        - a missing incoming timestamp never overwrites a stamped row.
        Returns True when the row was written.
        """
        symbol = str(quote.get("symbol") or "").strip().upper()
        if not symbol:
            return False
        existing = self.get_stored_quote(symbol)
        if existing:
            incoming_rank = self._quote_source_rank(quote.get("source"))
            existing_rank = self._quote_source_rank(existing.get("source"))
            if incoming_rank < existing_rank:
                return False
            incoming_ts = self._quote_ts_key(quote.get("timestamp"))
            existing_ts = self._quote_ts_key(existing.get("timestamp"))
            if incoming_rank == existing_rank:
                if not incoming_ts or (existing_ts and incoming_ts < existing_ts):
                    return False
        from datetime import datetime, timezone

        # Locked single write: raw connect().execute() from concurrent
        # requests interleaves on the shared connection (ConstraintException).
        self.storage.execute(
            """
            INSERT OR REPLACE INTO market_quotes
            (symbol, instrument_key, trading_symbol, exchange, segment, source,
             timestamp, last_price, prev_close, open, high, low, close, volume,
             average_price, year_high, year_low, day_change, day_change_pct,
             updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                symbol,
                quote.get("instrument_key"),
                quote.get("trading_symbol"),
                quote.get("exchange"),
                quote.get("segment"),
                quote.get("source"),
                quote.get("timestamp"),
                quote.get("last_price"),
                quote.get("prev_close"),
                quote.get("open"),
                quote.get("high"),
                quote.get("low"),
                quote.get("close"),
                quote.get("volume"),
                quote.get("average_price"),
                quote.get("year_high"),
                quote.get("year_low"),
                quote.get("day_change"),
                quote.get("day_change_pct"),
                datetime.now(timezone.utc),
            ],
        )
        return True

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