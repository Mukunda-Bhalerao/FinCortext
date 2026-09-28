"""Repository for macro observations and macro outputs.

Macro data is market-wide (India), not per-company: reads are keyed by
indicator, never by symbol — so company switching cannot misattribute it.
Observation ids are deterministic hashes of (indicator, period, value,
source), making re-ingestion idempotent.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime

from app.data.storage.duckdb_storage import DuckDBStorage
from app.domain.models.macro import MacroObservation, MacroOutput


def observation_id_for(
    indicator_id: str, period_end, value: float, source_name: str
) -> str:
    """Deterministic id so identical re-ingests replace rather than duplicate."""
    key = f"{indicator_id}|{period_end}|{value!r}|{source_name}"
    return "macro-" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]


def _iso(value) -> str | None:
    """ISO string for date/datetime values; passes strings/None through."""
    if value is None or isinstance(value, str):
        return value
    return value.isoformat()


class MacroRepository:
    def __init__(self, storage: DuckDBStorage):
        self.storage = storage

    # -- observations ------------------------------------------------------

    def save_observations(self, observations: list[MacroObservation]) -> int:
        if not observations:
            return 0
        rows = []
        for o in observations:
            if not o.observation_id:
                o.observation_id = observation_id_for(
                    o.indicator_id, o.period_end, o.value, o.source_name
                )
            rows.append(
                (
                    o.observation_id,
                    o.indicator_id,
                    o.value,
                    o.unit,
                    o.period_start,
                    o.period_end,
                    o.observed_at,
                    o.published_at,
                    o.available_at,
                    o.source_type.value,
                    o.source_name,
                    o.source_url,
                    o.content_hash,
                    o.notes,
                    o.ingested_at,
                )
            )
        self.storage.executemany(
            """
            INSERT OR REPLACE INTO macro_observations
            (observation_id, indicator_id, value, unit, period_start,
             period_end, observed_at, published_at, available_at,
             source_type, source_name, source_url, content_hash, notes,
             ingested_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        return len(rows)

    def get_series(
        self, indicator_id: str, as_of: datetime | None = None
    ) -> list[MacroObservation]:
        """Observations for one indicator, oldest period first.

        `as_of` filters to rows available at that time (point-in-time reads
        for future backtests); rows without a period sort last.
        """
        sql = "SELECT * FROM macro_observations WHERE indicator_id = ?"
        params: list = [indicator_id]
        if as_of is not None:
            sql += " AND available_at <= ?"
            params.append(as_of)
        sql += " ORDER BY period_end NULLS LAST, observed_at NULLS LAST"
        return [self._row_to_observation(r) for r in self.storage.fetch_all(sql, params)]

    def latest(self, indicator_id: str) -> MacroObservation | None:
        rows = self.get_series(indicator_id)
        dated = [o for o in rows if o.period_end is not None or o.observed_at is not None]
        if dated:
            return max(
                dated,
                key=lambda o: (o.period_end or o.observed_at),  # type: ignore[operator]
            )
        return rows[-1] if rows else None

    def indicators(self) -> list[str]:
        rows = self.storage.fetch_all(
            "SELECT DISTINCT indicator_id FROM macro_observations", []
        )
        return sorted(r["indicator_id"] for r in rows)

    def coverage(self) -> list[dict]:
        """Per-indicator storage summary for status displays."""
        rows = self.storage.fetch_all(
            """
            SELECT indicator_id, COUNT(*) AS n,
                   MAX(period_end) AS latest_period,
                   MAX(observed_at) AS latest_observed,
                   MAX(available_at) AS latest_available
            FROM macro_observations GROUP BY indicator_id
            """,
            [],
        )
        return [
            {
                "indicator_id": r["indicator_id"],
                "count": int(r["n"]),
                "latest_period": _iso(r["latest_period"]),
                "latest_observed": _iso(r["latest_observed"]),
                "latest_available": _iso(r["latest_available"]),
            }
            for r in rows
        ]

    def _row_to_observation(self, r: dict) -> MacroObservation:
        return MacroObservation(
            observation_id=r["observation_id"],
            indicator_id=r["indicator_id"],
            value=r["value"],
            unit=r["unit"],
            period_start=r["period_start"],
            period_end=r["period_end"],
            observed_at=r["observed_at"],
            published_at=r["published_at"],
            available_at=r["available_at"],
            source_type=r["source_type"],
            source_name=r["source_name"],
            source_url=r["source_url"],
            content_hash=r["content_hash"],
            notes=r["notes"],
            ingested_at=r["ingested_at"],
        )

    # -- outputs -----------------------------------------------------------

    def save_output(self, output: MacroOutput) -> str:
        output_id = str(uuid.uuid4())
        self.storage.execute(
            """
            INSERT INTO macro_outputs
            (output_id, generated_at, overall_signal, confidence, status,
             score, factors_json, rationale, data_through_json, limitations_json,
             methodology)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                output_id,
                output.generated_at,
                output.overall_signal.value,
                output.confidence,
                output.status,
                output.score,
                output.model_dump_json(),
                output.rationale,
                json.dumps(output.data_through),
                json.dumps(output.data_limitations),
                output.methodology,
            ],
        )
        return output_id

    def latest_output(self) -> dict | None:
        rows = self.storage.fetch_all(
            "SELECT * FROM macro_outputs ORDER BY generated_at DESC LIMIT 1", []
        )
        return rows[0] if rows else None

    def history(self, limit: int = 20) -> list[dict]:
        return self.storage.fetch_all(
            "SELECT * FROM macro_outputs ORDER BY generated_at DESC LIMIT ?",
            [max(1, min(int(limit), 100))],
        )
