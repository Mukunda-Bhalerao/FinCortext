"""Repository for portfolio synthesis views.

One row per run, keyed by company symbol — switching companies can only ever
read back the selected company's own synthesis. The full view (including all
underlying perspectives) is embedded as JSON, so history never depends on the
analyst output tables still holding the same rows.
"""

from __future__ import annotations

import uuid

from app.data.storage.duckdb_storage import DuckDBStorage
from app.domain.models.portfolio import PortfolioView


class PortfolioRepository:
    def __init__(self, storage: DuckDBStorage):
        self.storage = storage

    def save_output(self, output: PortfolioView) -> str:
        output_id = str(uuid.uuid4())
        self.storage.execute(
            """
            INSERT INTO portfolio_outputs
            (output_id, entity_id, generated_at, view_json, status)
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                output_id,
                output.entity_id,
                output.generated_at,
                output.model_dump_json(),
                output.status,
            ],
        )
        return output_id

    def latest(self, symbol: str) -> dict | None:
        rows = self.storage.fetch_all(
            "SELECT * FROM portfolio_outputs WHERE entity_id = ? "
            "ORDER BY generated_at DESC LIMIT 1",
            [symbol.upper()],
        )
        return rows[0] if rows else None

    def latest_view(self, symbol: str) -> dict | None:
        """Latest stored synthesis as a full PortfolioView dict.

        `view_json` holds the complete model dump, so no recomputation
        (and no fabrication) is involved — purely a stored read.
        """
        import json

        row = self.latest(symbol)
        if row is None:
            return None
        try:
            return json.loads(row["view_json"])
        except (TypeError, ValueError, KeyError):
            return None

    def history(self, symbol: str, limit: int = 20) -> list[dict]:
        return self.storage.fetch_all(
            "SELECT * FROM portfolio_outputs WHERE entity_id = ? "
            "ORDER BY generated_at DESC LIMIT ?",
            [symbol.upper(), max(1, min(int(limit), 100))],
        )
