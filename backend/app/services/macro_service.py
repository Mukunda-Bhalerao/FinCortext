"""Macro data service: providers → validation → storage → provenance.

Orchestration for market-wide macro indicators (RBI/MoSPI curated series +
yfinance market gauges). Per-indicator failure isolation: one broken series
never blocks the rest. Macro data is market-wide — nothing here is keyed by
company symbol, so company switching cannot misattribute it.
"""

from __future__ import annotations

import hashlib

from app.core.exceptions import ProviderError
from app.core.logging import get_logger
from app.data.macro.indicators import get_indicator, indicator_ids
from app.data.validation.macro_validation import validate_bundle
from app.domain.contracts.providers import MacroDataProvider
from app.domain.models.base import DataStatus
from app.domain.models.macro import MacroObservation
from app.repositories.macro_repository import MacroRepository
from app.repositories.provenance_repository import ProvenanceRepository

logger = get_logger("services.macro")


class MacroService:
    def __init__(
        self,
        providers: list[MacroDataProvider],
        macro_repo: MacroRepository,
        provenance_repo: ProvenanceRepository,
    ):
        self.providers = list(providers)
        self.macro_repo = macro_repo
        self.provenance_repo = provenance_repo

    # -- refresh ------------------------------------------------------------

    def _provider_for(self, indicator_id: str) -> MacroDataProvider:
        meta = get_indicator(indicator_id)
        for provider in self.providers:
            if meta.get("source") == "curated" and provider.name == "curated_official":
                return provider
            if meta.get("source") == "yfinance" and provider.name == "yfinance_macro":
                return provider
        raise ProviderError(
            f"No macro provider wired for indicator '{indicator_id}'.",
            details={"indicator": indicator_id},
        )

    def refresh_indicator(self, indicator_id: str) -> dict:
        """Fetch, validate and store one indicator (idempotent re-ingests)."""
        meta = get_indicator(indicator_id)  # validates the id
        provider = self._provider_for(indicator_id)
        bundle = provider.fetch_indicator(indicator_id)
        validated = validate_bundle(indicator_id, bundle)
        warnings = list(bundle.get("warnings", []))

        content_hash = hashlib.sha256(
            repr(sorted(
                (p["period_end"], p["value"]) for p in validated.points
            )).encode("utf-8")
        ).hexdigest()
        observations = [
            MacroObservation(
                indicator_id=indicator_id,
                value=p["value"],
                unit=validated.unit,
                period_start=p["period_start"],
                period_end=p["period_end"],
                observed_at=p["period_end"],
                published_at=p["published_at"],
                source_type="yfinance"
                if meta.get("source") == "yfinance"
                else "unknown",
                source_name=bundle.get("source_name") or meta.get("source", "unknown"),
                source_url=p["source_url"],
                content_hash=content_hash,
                notes=p["notes"],
            )
            for p in validated.points
        ]
        saved = self.macro_repo.save_observations(observations)
        self.provenance_repo.record(
            "macro_refresh",
            entity_id="MACRO_INDIA",
            source_type=provider.name,
            source_name=bundle.get("source_name") or meta.get("source", "unknown"),
            content_hash=content_hash,
            rows_ingested=saved,
            rows_rejected=len(validated.rejected),
            detail=f"indicator={indicator_id}; warnings={len(warnings)}",
        )
        logger.info(
            "Macro refresh %s: %d stored, %d rejected, %d warnings",
            indicator_id, saved, len(validated.rejected), len(warnings),
        )
        return {
            "indicator_id": indicator_id,
            "status": DataStatus.LIVE.value if saved else DataStatus.UNAVAILABLE.value,
            "observations_stored": saved,
            "rejected": validated.rejected,
            "warnings": warnings,
            "source": bundle.get("source_name"),
        }

    def refresh_all(self, indicator_ids: list[str] | None = None) -> dict:
        """Refresh all (or selected) indicators; failures are isolated."""
        targets = indicator_ids or indicator_ids_all()
        results = []
        for indicator_id in targets:
            try:
                results.append(self.refresh_indicator(indicator_id))
            except ProviderError as exc:
                logger.error("Macro refresh failed for %s: %s", indicator_id, exc.message)
                results.append(
                    {
                        "indicator_id": indicator_id,
                        "status": DataStatus.ERROR.value,
                        "error": exc.message,
                    }
                )
        ok = sum(1 for r in results if r.get("status") == DataStatus.LIVE.value)
        return {
            "indicators_requested": len(results),
            "indicators_ok": ok,
            "results": results,
        }

    # -- reads ---------------------------------------------------------------

    def get_series(self, indicator_id: str) -> dict:
        """Stored series for one indicator with explicit status."""
        meta = get_indicator(indicator_id)
        obs = self.macro_repo.get_series(indicator_id)
        latest = self.macro_repo.latest(indicator_id)
        return {
            "indicator_id": indicator_id,
            "label": meta.get("label", indicator_id),
            "unit": meta.get("unit"),
            "status": DataStatus.CACHED.value if obs else DataStatus.UNAVAILABLE.value,
            "count": len(obs),
            "latest": _observation_dict(latest),
            "observations": [_observation_dict(o) for o in obs],
        }

    def get_coverage(self) -> dict:
        """Per-indicator storage summary for status displays."""
        return {"indicators": self.macro_repo.coverage()}

    def latest_view(self) -> dict | None:
        """Latest stored macro environment view as a full MacroOutput dict.

        `factors_json` holds the complete model dump, so no recomputation
        (and no fabrication) is involved — purely a stored read.
        """
        import json

        row = self.macro_repo.latest_output()
        if row is None:
            return None
        try:
            return json.loads(row["factors_json"])
        except (TypeError, ValueError, KeyError):
            return None


def indicator_ids_all() -> list[str]:
    return indicator_ids()


def _observation_dict(o) -> dict | None:
    if o is None:
        return None
    return {
        "value": o.value,
        "unit": o.unit,
        "period_start": o.period_start.isoformat() if o.period_start else None,
        "period_end": o.period_end.isoformat() if o.period_end else None,
        "observed_at": o.observed_at.isoformat() if o.observed_at else None,
        "published_at": o.published_at.isoformat() if o.published_at else None,
        "available_at": o.available_at.isoformat() if o.available_at else None,
        "source_name": o.source_name,
        "source_url": o.source_url,
        "notes": o.notes,
    }
