"""Repository for web-research reports (Gemini grounding evidence).

Persists enrichment outputs — company profiles, peer discoveries, news
digests — with their sources and confidence. Research rows are EVIDENCE
ONLY: they are never stored as market prices, never stored as NewsAPI
articles, and never scored by FinBERT as news.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from app.data.storage.duckdb_storage import DuckDBStorage


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ResearchRepository:
    def __init__(self, storage: DuckDBStorage):
        self.storage = storage

    def save_report(
        self,
        entity_id: str,
        report_type: str,
        subject: str,
        payload: dict,
        *,
        confidence: float | None = None,
        sources: list | None = None,
        model: str | None = None,
        source_name: str = "gemini_research",
    ) -> str:
        """Upsert one research report (idempotent per entity+type+subject)."""
        entity = (entity_id or "").strip().upper()
        rtype = (report_type or "").strip()
        subj = (subject or "").strip()
        report_id = hashlib.sha256(
            f"{entity}|{rtype}|{subj}".encode("utf-8", errors="replace")
        ).hexdigest()
        self.storage.execute(
            """
            INSERT OR REPLACE INTO research_reports
            (report_id, entity_id, report_type, subject, payload_json,
             confidence, sources_json, model, source_name, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                report_id,
                entity,
                rtype,
                subj,
                json.dumps(payload or {}, ensure_ascii=False, default=str),
                confidence,
                json.dumps(sources or [], ensure_ascii=False, default=str),
                model,
                source_name,
                _utcnow(),
            ],
        )
        return report_id

    def latest_report(self, entity_id: str, report_type: str) -> dict | None:
        """Latest stored report of one type for one entity (None when absent)."""
        rows = self.storage.fetch_all(
            "SELECT * FROM research_reports WHERE entity_id = ? AND report_type = ? "
            "ORDER BY created_at DESC LIMIT 1",
            [(entity_id or "").strip().upper(), (report_type or "").strip()],
        )
        if not rows:
            return None
        return self._decode(rows[0])

    def list_reports(self, entity_id: str, limit: int = 20) -> list[dict]:
        """Stored reports for one entity, newest first."""
        rows = self.storage.fetch_all(
            "SELECT * FROM research_reports WHERE entity_id = ? "
            "ORDER BY created_at DESC LIMIT ?",
            [(entity_id or "").strip().upper(), max(1, int(limit or 20))],
        )
        return [self._decode(r) for r in rows]

    def count(self, entity_id: str | None = None) -> int:
        if entity_id:
            rows = self.storage.fetch_all(
                "SELECT COUNT(*) AS n FROM research_reports WHERE entity_id = ?",
                [entity_id.upper()],
            )
        else:
            rows = self.storage.fetch_all("SELECT COUNT(*) AS n FROM research_reports")
        return int(rows[0]["n"]) if rows else 0

    @staticmethod
    def _decode(row: dict) -> dict:
        out = dict(row)
        for key in ("payload_json", "sources_json"):
            raw = out.get(key)
            if isinstance(raw, str) and raw:
                try:
                    out[key[:-5]] = json.loads(raw)
                except ValueError:
                    out[key[:-5]] = None
        created = out.get("created_at")
        out["created_at"] = created.isoformat() if hasattr(created, "isoformat") else created
        return out
