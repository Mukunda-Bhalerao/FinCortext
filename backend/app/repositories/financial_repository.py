"""Repository for financial observations and filing documents."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from app.data.storage.duckdb_storage import DuckDBStorage
from app.domain.models.financial import FilingDocument, FinancialObservation


class FinancialRepository:
    def __init__(self, storage: DuckDBStorage):
        self.storage = storage

    # -- observations -------------------------------------------------------

    def save_observations(self, observations: list[FinancialObservation]) -> int:
        if not observations:
            return 0
        rows = []
        for o in observations:
            rows.append(
                (
                    str(uuid.uuid4()),
                    o.entity_id,
                    o.metric,
                    o.value,
                    o.unit,
                    o.currency,
                    o.period_start,
                    o.period_end,
                    o.statement_type.value,
                    o.consolidation_basis.value,
                    o.fiscal_year,
                    o.source_type.value,
                    o.source_name,
                    o.source_reference,
                    o.raw_document_reference,
                    o.content_hash,
                    o.filing_date,
                    o.published_at,
                    o.available_at,
                    o.schema_version,
                    o.ingested_at,
                )
            )
        self.storage.connect().executemany(
            """
            INSERT OR REPLACE INTO financial_observations
            (observation_id, entity_id, metric, value, unit, currency,
             period_start, period_end, statement_type, consolidation_basis,
             fiscal_year, source_type, source_name, source_reference,
             raw_document_reference, content_hash, filing_date, published_at,
             available_at, schema_version, ingested_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        return len(rows)

    def get_observations(
        self,
        entity_id: str,
        metric: str | None = None,
        as_of: datetime | None = None,
        latest_period: bool = True,
    ) -> list[FinancialObservation]:
        """Point-in-time aware observation lookup.

        `as_of` filters to observations whose available_at <= as_of, so future
        backtests never see information that was not public yet.
        """
        sql = "SELECT * FROM financial_observations WHERE entity_id = ?"
        params: list = [entity_id.upper()]
        if metric is not None:
            sql += " AND metric = ?"
            params.append(metric)
        if as_of is not None:
            sql += " AND available_at <= ?"
            params.append(as_of)
        rows = self.storage.fetch_all(sql, params)
        obs = [self._row_to_observation(r) for r in rows]
        if latest_period and obs:
            latest_end = max(
                (o.period_end for o in obs if o.period_end is not None), default=None
            )
            if latest_end is not None:
                obs = [o for o in obs if o.period_end == latest_end]
        return obs

    def latest_metric_value(
        self,
        entity_id: str,
        metric: str,
        as_of: datetime | None = None,
    ) -> FinancialObservation | None:
        """Most recent observation for one metric (by period_end)."""
        obs = self.get_observations(entity_id, metric=metric, as_of=as_of, latest_period=False)
        if not obs:
            return None
        obs.sort(key=lambda o: (o.period_end or date.min), reverse=True)
        return obs[0]

    def delete_observations(self, entity_id: str, source_type: str) -> int:
        """Delete observations for one entity from one source type.

        Used by provider refresh flows (refresh replaces the last provider
        snapshot instead of accumulating duplicates). Official filing
        observations are never touched by this path — callers pass the
        provider source type explicitly.
        """
        rows = self.storage.fetch_all(
            "SELECT COUNT(*) AS n FROM financial_observations "
            "WHERE entity_id = ? AND source_type = ?",
            [entity_id.upper(), source_type],
        )
        count = int(rows[0]["n"]) if rows else 0
        if count:
            self.storage.execute(
                "DELETE FROM financial_observations WHERE entity_id = ? AND source_type = ?",
                [entity_id.upper(), source_type],
            )
        return count

    def _row_to_observation(self, r: dict) -> FinancialObservation:
        from app.domain.models.financial import ConsolidationBasis, StatementType

        return FinancialObservation(
            entity_id=r["entity_id"],
            metric=r["metric"],
            value=r["value"],
            unit=r["unit"],
            currency=r["currency"],
            period_start=r["period_start"],
            period_end=r["period_end"],
            statement_type=StatementType(r["statement_type"]),
            consolidation_basis=ConsolidationBasis(r["consolidation_basis"]),
            fiscal_year=r["fiscal_year"],
            source_type=r["source_type"],
            source_name=r["source_name"],
            source_reference=r["source_reference"],
            raw_document_reference=r["raw_document_reference"],
            content_hash=r["content_hash"],
            filing_date=r["filing_date"],
            published_at=r["published_at"],
            available_at=r["available_at"],
            schema_version=r["schema_version"],
            ingested_at=r["ingested_at"],
        )

    # -- filing documents -----------------------------------------------------

    def save_document(self, doc: FilingDocument) -> None:
        self.storage.execute(
            """
            INSERT OR REPLACE INTO filing_documents
            (document_id, entity_id, document_type, file_name, file_path,
             content_hash, source_type, source_name, source_url, filing_date,
             published_at, ingested_at, observation_count, parse_warnings)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                doc.document_id,
                doc.entity_id,
                doc.document_type,
                doc.file_name,
                doc.file_path,
                doc.content_hash,
                doc.source_type.value,
                doc.source_name,
                doc.source_url,
                doc.filing_date,
                doc.published_at,
                doc.ingested_at,
                doc.observation_count,
                "; ".join(doc.parse_warnings) if doc.parse_warnings else None,
            ],
        )

    def get_documents(self, entity_id: str | None = None) -> list[dict]:
        if entity_id:
            return self.storage.fetch_all(
                "SELECT * FROM filing_documents WHERE entity_id = ? ORDER BY ingested_at DESC",
                [entity_id.upper()],
            )
        return self.storage.fetch_all("SELECT * FROM filing_documents ORDER BY ingested_at DESC")

    def document_exists_by_hash(self, content_hash: str) -> bool:
        rows = self.storage.fetch_all(
            "SELECT document_id FROM filing_documents WHERE content_hash = ? LIMIT 1",
            [content_hash],
        )
        return bool(rows)