"""Repository for persisting and retrieving standardized AgentOutputs."""

from __future__ import annotations

import uuid
from typing import Any

from app.data.storage.duckdb_storage import DuckDBStorage
from app.domain.models.agent_output import AgentOutput


class AgentOutputRepository:
    def __init__(self, storage: DuckDBStorage):
        self.storage = storage

    def save(self, output: AgentOutput) -> str:
        output_id = str(uuid.uuid4())
        d = output.to_storage_dict()
        self.storage.execute(
            """
            INSERT INTO agent_outputs
            (output_id, agent_id, entity_id, score, signal, confidence,
             factors_json, rationale, generated_at, data_version, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                output_id,
                d["agent_id"],
                d["entity_id"],
                d["score"],
                d["signal"],
                d["confidence"],
                d["factors_json"],
                d["rationale"],
                d["generated_at"],
                d["data_version"],
                d["status"],
            ],
        )
        return output_id

    def list_outputs(
        self,
        agent_id: str | None = None,
        entity_id: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        sql = "SELECT * FROM agent_outputs WHERE 1=1"
        params: list[Any] = []
        if agent_id:
            sql += " AND agent_id = ?"
            params.append(agent_id)
        if entity_id:
            sql += " AND entity_id = ?"
            params.append(entity_id.upper())
        sql += " ORDER BY generated_at DESC LIMIT ?"
        params.append(limit)
        return self.storage.fetch_all(sql, params)

    def latest_output(self, agent_id: str, entity_id: str) -> dict | None:
        rows = self.list_outputs(agent_id=agent_id, entity_id=entity_id, limit=1)
        return rows[0] if rows else None