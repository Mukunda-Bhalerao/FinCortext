"""Fundamentals service: provider → normalize → validate → storage → provenance.

Orchestration layer for provider-supplied fundamentals (annual statements +
snapshot ratios). This is the FALLBACK/ENRICHMENT path — ingested official
filings remain the primary source of truth, and every observation built here
is labeled with the provider's own name and a `provider` source type so the
two are never confused downstream.

No provider is wired in production after the Upstox consolidation: refreshes
raise ProviderUnavailableError and the preparation flow degrades to stored
observations (pre-consolidation imports relabeled `legacy_import`). Official
filings are unaffected.

Point-in-time honesty: annual statement values carry real fiscal period_end
dates; snapshot ratios (P/E, ROE) have no statement period, so their
available_at falls back to ingestion time. The refresh result states this
limitation explicitly.

Refresh replaces the previous provider snapshot for the symbol (scoped delete
by source type) instead of accumulating duplicates. Official filing
observations are never touched.
"""

from __future__ import annotations

import hashlib
from datetime import date, timedelta

from app.core.exceptions import ProviderError, ProviderUnavailableError
from app.core.logging import get_logger
from app.data.universe.universe_config import get_universe, get_universe_entry
from app.data.validation.fundamentals_validation import validate_metrics
from app.domain.contracts.providers import FundamentalDataProvider
from app.domain.models.base import DataStatus, DataSourceType
from app.domain.models.financial import ConsolidationBasis, FinancialObservation, StatementType
from app.repositories.financial_repository import FinancialRepository
from app.repositories.provenance_repository import ProvenanceRepository

logger = get_logger("services.fundamentals")

ANNUAL_METRICS = ("total_revenue", "net_income", "total_assets", "total_equity", "total_debt")
SNAPSHOT_METRICS = ("pe_ratio", "roe")

SNAPSHOT_LIMITATION = (
    "Snapshot ratios (P/E, ROE) carry no statement period; "
    "available_at = ingestion time. Do not use them for historical evaluation."
)

NO_PROVIDER_MESSAGE = (
    "No fundamentals provider is configured — provider refresh unavailable. "
    "Ingested official filings remain the primary source; stored "
    "pre-consolidation observations (legacy import) remain usable."
)


class FundamentalsService:
    def __init__(
        self,
        provider: FundamentalDataProvider | None,
        financial_repo: FinancialRepository,
        provenance_repo: ProvenanceRepository,
    ):
        self.provider = provider
        self.financial_repo = financial_repo
        self.provenance_repo = provenance_repo

    # -- refresh ------------------------------------------------------------

    def refresh_symbol(self, symbol: str) -> dict:
        """Fetch, validate, and store fundamentals for one universe symbol.

        Raises ProviderUnavailableError when no provider is configured —
        callers degrade honestly to stored observations.
        """
        entry = get_universe_entry(symbol)
        if self.provider is None:
            raise ProviderUnavailableError(NO_PROVIDER_MESSAGE)
        bundle = self.provider.fetch_fundamentals(entry.symbol)

        content_hash = hashlib.sha256(
            repr((bundle.get("annual"), bundle.get("snapshot"))).encode("utf-8")
        ).hexdigest()
        observations: list[FinancialObservation] = []
        rejected: list[dict] = []
        warnings = list(bundle.get("warnings", []))

        for row in bundle.get("annual", []):
            period_end = row.get("period_end")
            if not isinstance(period_end, date):
                rejected.append({"metric": "*", "reason": f"unparseable period: {period_end!r}"})
                continue
            candidates = {m: row.get(m) for m in ANNUAL_METRICS}
            validated = validate_metrics(candidates)
            for r in validated.rejected:
                rejected.append({**r, "period_end": period_end.isoformat()})
            for metric, value in validated.valid.items():
                    statement = (
                        StatementType.INCOME_STATEMENT
                        if metric in ("total_revenue", "net_income")
                        else StatementType.BALANCE_SHEET
                    )
                    observations.append(
                        FinancialObservation(
                            entity_id=entry.symbol,
                            metric=metric,
                            value=value,
                            unit="INR",
                            currency=bundle.get("currency", "INR"),
                            period_start=period_end - timedelta(days=365),
                            period_end=period_end,
                            statement_type=statement,
                            consolidation_basis=ConsolidationBasis.UNKNOWN,
                            fiscal_year=str(period_end.year),
                            source_type=DataSourceType.PROVIDER,
                            source_name=f"{self.provider.name} (annual statements)",
                            source_reference=bundle.get("ticker"),
                            content_hash=content_hash,
                        )
                    )

        snapshot = bundle.get("snapshot", {}) or {}
        snap_validated = validate_metrics({m: snapshot.get(m) for m in SNAPSHOT_METRICS})
        for r in snap_validated.rejected:
            rejected.append({**r, "period_end": None})
        for metric, value in snap_validated.valid.items():
            # Snapshot ratios are unitless multiples; P/E is scored directly.
            observations.append(
                FinancialObservation(
                    entity_id=entry.symbol,
                    metric=metric,
                    value=value,
                    unit="ratio",
                    currency=bundle.get("currency", "INR"),
                    period_end=None,
                    statement_type=StatementType.OTHER,
                    consolidation_basis=ConsolidationBasis.UNKNOWN,
                    source_type=DataSourceType.PROVIDER,
                    source_name=f"{self.provider.name} (snapshot ratios)",
                    source_reference=bundle.get("ticker"),
                    content_hash=content_hash,
                )
            )

        # Replace the previous provider snapshot (scoped by source type).
        replaced = self.financial_repo.delete_observations(
            entry.symbol, DataSourceType.PROVIDER.value
        )
        saved = self.financial_repo.save_observations(observations) if observations else 0
        metrics = sorted({o.metric for o in observations})

        self.provenance_repo.record(
            "fundamentals_refresh",
            entity_id=entry.symbol,
            source_type=self.provider.name,
            source_name=f"{self.provider.name} (annual statements)",
            rows_ingested=saved,
            rows_rejected=len(rejected),
            detail=f"metrics={metrics}; replaced={replaced}; warnings={len(warnings)}",
        )
        logger.info(
            "Fundamentals refresh %s: %d stored (%s), %d rejected, %d warnings",
            entry.symbol, saved, metrics, len(rejected), len(warnings),
        )
        limitations = [SNAPSHOT_LIMITATION] if any(
            o.metric in SNAPSHOT_METRICS for o in observations
        ) else []
        return {
            "symbol": entry.symbol,
            "status": DataStatus.LIVE.value if saved else DataStatus.UNAVAILABLE.value,
            "observations_stored": saved,
            "observations_replaced": replaced,
            "metrics": metrics,
            "warnings": warnings,
            "rejected": rejected,
            "limitations": limitations,
        }

    def refresh_universe(self, symbols: list[str] | None = None) -> dict:
        """Refresh all (or selected) universe symbols; failures are isolated."""
        results = []
        for entry in get_universe():
            if symbols and entry.symbol not in {s.upper() for s in symbols}:
                continue
            try:
                results.append(self.refresh_symbol(entry.symbol))
            except ProviderError as exc:
                logger.error(
                    "Fundamentals refresh failed for %s: %s", entry.symbol, exc.message
                )
                results.append(
                    {
                        "symbol": entry.symbol,
                        "status": DataStatus.ERROR.value,
                        "error": exc.message,
                    }
                )
        stored = sum(1 for r in results if r.get("status") == DataStatus.LIVE.value)
        return {
            "provider": self.provider.name,
            "symbols_requested": len(results),
            "symbols_ok": stored,
            "results": results,
        }

    # -- coverage -----------------------------------------------------------

    def get_coverage(self, symbol: str) -> dict:
        """Metric coverage for one symbol: latest value per metric with source."""
        entry = get_universe_entry(symbol)
        metrics: dict[str, dict] = {}
        # Canonical metrics the Firm Analyst can consume.
        for metric in (*ANNUAL_METRICS, *SNAPSHOT_METRICS, "operating_profit", "eps"):
            obs = self.financial_repo.latest_metric_value(entry.symbol, metric)
            if obs is None:
                continue
            metrics[metric] = {
                "value": obs.value,
                "unit": obs.unit,
                "period_end": obs.period_end.isoformat() if obs.period_end else None,
                "source_type": obs.source_type.value
                if hasattr(obs.source_type, "value")
                else str(obs.source_type),
                "source_name": obs.source_name,
                "available_at": obs.available_at.isoformat() if obs.available_at else None,
            }
        official = any(m["source_type"] == "official_filing" for m in metrics.values())
        provider = any(m["source_type"] in ("provider", "legacy_import") for m in metrics.values())
        return {
            "symbol": entry.symbol,
            "name": entry.name,
            "status": DataStatus.CACHED.value if metrics else DataStatus.UNAVAILABLE.value,
            "metric_count": len(metrics),
            "has_official": official,
            "has_provider": provider,
            "metrics": metrics,
        }
