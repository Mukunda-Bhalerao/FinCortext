"""Repository for data provenance / ingestion event records."""

from __future__ import annotations

import uuid
from datetime import datetime

from app.data.storage.duckdb_storage import DuckDBStorage
from app.domain.models.base import utcnow


class ProvenanceRepository:
    def __init__(self, storage: DuckDBStorage):
        self.storage = storage

    def record(
        self,
        event_type: str,
        *,
        entity_id: str | None = None,
        source_type: str = "unknown",
        source_name: str = "unknown",
        content_hash: str | None = None,
        rows_ingested: int = 0,
        rows_rejected: int = 0,
        detail: str | None = None,
        ingested_at: datetime | None = None,
    ) -> str:
        event_id = str(uuid.uuid4())
        self.storage.execute(
            """
            INSERT INTO data_provenance
            (event_id, event_type, entity_id, source_type, source_name,
             content_hash, rows_ingested, rows_rejected, detail, ingested_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                event_id,
                event_type,
                entity_id,
                source_type,
                source_name,
                content_hash,
                rows_ingested,
                rows_rejected,
                detail,
                ingested_at or utcnow(),
            ],
        )
        return event_id

    def list_events(self, entity_id: str | None = None, limit: int = 100) -> list[dict]:
        if entity_id:
            return self.storage.fetch_all(
                "SELECT * FROM data_provenance WHERE entity_id = ? ORDER BY ingested_at DESC LIMIT ?",
                [entity_id.upper(), limit],
            )
        return self.storage.fetch_all(
            "SELECT * FROM data_provenance ORDER BY ingested_at DESC LIMIT ?", [limit]
        )