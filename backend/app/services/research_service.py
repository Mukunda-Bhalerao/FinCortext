"""Research service: Gemini provider → validation → storage → provenance.

Orchestration layer for web-research/enrichment (company classification,
peer discovery, news digests). Business logic lives here, not in routes.

Degradation contract (mirrors NewsService):
- Missing GEMINI_API_KEY  -> UNAVAILABLE status dicts (no raise); every
  unrelated module keeps working.
- Provider/rate/network failure -> ERROR status dicts with safe messages.
- Validation failures (empty sector, unusable peers) -> stored as evidence
  but flagged unusable — never applied blindly, never fabricated.
- The service never scores, never prices, never replaces deterministic
  financial calculations.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

from app.core.config import Settings, settings
from app.core.exceptions import ProviderError, ProviderUnavailableError
from app.core.logging import get_logger
from app.domain.contracts.providers import ResearchProvider
from app.domain.models.base import DataStatus
from app.repositories.provenance_repository import ProvenanceRepository
from app.repositories.research_repository import ResearchRepository

logger = get_logger("services.research")

# Minimum Gemini self-reported confidence before a classification is applied
# to a company's metadata. Below this the report is kept as evidence only.
MIN_APPLY_CONFIDENCE = 0.35


class ResearchService:
    def __init__(
        self,
        provider: ResearchProvider,
        research_repo: ResearchRepository,
        provenance_repo: ProvenanceRepository,
        config: Settings | None = None,
    ):
        self.provider = provider
        self.research_repo = research_repo
        self.provenance_repo = provenance_repo
        self.config = config or settings

    # -- status ------------------------------------------------------------------

    def get_status(self) -> dict:
        """Provider configuration status (safe for health/UI display)."""
        configured = getattr(self.provider, "is_configured", True)
        return {
            "provider": self.provider.name,
            "configured": configured,
            "model": getattr(self.provider, "model_name", None),
            "status": (
                DataStatus.LIVE.value if configured else DataStatus.UNAVAILABLE.value
            ),
            "message": (
                None
                if configured
                else "GEMINI_API_KEY is not configured — web research and "
                "enrichment are unavailable. Structured providers still work."
            ),
        }

    def verify(self) -> dict:
        """Check the configured model is reachable (no generation).

        Returns {"ok", "model", "error"|None} with sanitized diagnostics.
        Used by the manual smoke test and ``GET /api/research/verify``.
        """
        verify = getattr(self.provider, "verify_model", None)
        if not callable(verify):
            return {
                "ok": False,
                "model": getattr(self.provider, "model_name", None),
                "error": "Provider does not support verification.",
            }
        try:
            return verify()
        except Exception as exc:  # never propagate from a diagnostic
            logger.exception("Research verification failed")
            return {
                "ok": False,
                "model": getattr(self.provider, "model_name", None),
                "error": f"{type(exc).__name__}",
            }

    def record_classification(
        self,
        symbol: str,
        *,
        sector: str | None,
        industry: str | None,
        company_name: str | None = None,
        source: str = "structured",
        confidence: float | None = None,
        isin: str | None = None,
    ) -> str | None:
        """Persist a structured (non-Gemini) classification as evidence.

        Used for official NSE-CSV classifications so the applied
        sector/industry is auditable with its source + confidence, exactly
        like Gemini company profiles. Never raises (evidence must not break
        preparation); returns the report_id or None.
        """
        entity = (symbol or "").strip().upper()
        try:
            report_id = self.research_repo.save_report(
                entity,
                "industry_classification",
                company_name or entity,
                {
                    "company_name": company_name or entity,
                    "sector": sector,
                    "industry": industry,
                    "isin": isin,
                },
                confidence=confidence,
                sources=[{"title": "NSE / provider instrument metadata", "url": None}],
                model=None,
                source_name=source,
            )
            self.provenance_repo.record(
                "research_classification",
                entity_id=entity,
                source_type=source,
                source_name=source,
                rows_ingested=1,
                rows_rejected=0,
                detail=f"sector={sector}; industry={industry}",
            )
            return report_id
        except Exception as exc:
            logger.warning("Classification persist failed for %s: %s", entity, type(exc).__name__)
            return None

    def _unavailable(self, message: str) -> dict:
        return {
            "status": DataStatus.UNAVAILABLE.value,
            "provider": self.provider.name,
            "message": message,
        }

    def _error(self, entity: str, kind: str, message: str) -> dict:
        logger.error("Research %s failed for %s: %s", kind, entity, message)
        try:
            self.provenance_repo.record(
                f"research_{kind}_failed",
                entity_id=entity.upper(),
                source_type=self.provider.name,
                source_name=self.provider.name,
                rows_ingested=0,
                rows_rejected=0,
                detail=message,
            )
        except Exception:
            pass
        return {
            "status": DataStatus.ERROR.value,
            "provider": self.provider.name,
            "message": message,
        }

    # -- company classification ----------------------------------------------------

    def enrich_company(self, symbol: str, company_name: str) -> dict:
        """Grounded sector/industry classification for one company.

        Returns {"status", "sector"|None, "industry"|None, "confidence",
        "business_description", "sources", "usable", "report_id"|None}.
        `usable` is True only when sector+industry are present AND confidence
        meets MIN_APPLY_CONFIDENCE — otherwise the caller must NOT apply.
        """
        entity = (symbol or "").strip().upper()
        if not getattr(self.provider, "is_configured", True):
            return {
                **self._unavailable(
                    "GEMINI_API_KEY is not configured — company enrichment unavailable."
                ),
                "usable": False,
            }
        try:
            result = self.provider.research_company(entity, company_name or entity)
        except ProviderUnavailableError as exc:
            logger.warning("Company research unavailable for %s: %s", entity, exc.message)
            return {**self._unavailable(exc.message), "usable": False}
        except ProviderError as exc:
            return {**self._error(entity, "company", exc.message), "usable": False}
        except Exception as exc:  # never propagate provider crashes
            logger.exception("Unexpected research failure for %s", entity)
            return {**self._error(entity, "company", f"{type(exc).__name__}"), "usable": False}

        sector = (result.get("sector") or "").strip() or None
        industry = (result.get("industry") or "").strip() or None
        try:
            confidence = float(result.get("confidence", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0
        sources = result.get("sources") or []
        usable = bool(sector and industry) and confidence >= MIN_APPLY_CONFIDENCE
        report_id = None
        try:
            report_id = self.research_repo.save_report(
                entity,
                "company_profile",
                company_name or entity,
                {
                    "company_name": result.get("company_name"),
                    "sector": sector,
                    "industry": industry,
                    "business_description": result.get("business_description"),
                    "peers_suggested": result.get("peers") or [],
                    "usable": usable,
                },
                confidence=confidence,
                sources=sources,
                model=result.get("model"),
            )
            self.provenance_repo.record(
                "research_company",
                entity_id=entity,
                source_type=self.provider.name,
                source_name=self.provider.name,
                rows_ingested=1,
                rows_rejected=0,
                detail=f"sector={sector}; industry={industry}; usable={usable}",
            )
        except Exception as exc:
            logger.warning("Research persist failed for %s: %s", entity, type(exc).__name__)
        logger.info(
            "Company research for %s: sector=%s industry=%s usable=%s",
            entity, sector, industry, usable,
        )
        return {
            "status": DataStatus.LIVE.value if usable else DataStatus.UNAVAILABLE.value,
            "provider": self.provider.name,
            "sector": sector,
            "industry": industry,
            "confidence": confidence,
            "business_description": result.get("business_description"),
            "sources": sources,
            "usable": usable,
            "report_id": report_id,
        }

    # -- peer discovery --------------------------------------------------------------

    def discover_peers(
        self,
        symbol: str,
        company_name: str,
        sector: str,
        industry: str,
        *,
        max_peers: int = 8,
    ) -> dict:
        """Web-researched peer CANDIDATES (Upstox validation happens downstream).

        Returns {"status", "peers": [{symbol, name, reason}], "sources",
        "report_id"|None}. An empty candidate list is UNAVAILABLE, never
        padded with guesses.
        """
        entity = (symbol or "").strip().upper()
        if not getattr(self.provider, "is_configured", True):
            return self._unavailable(
                "GEMINI_API_KEY is not configured — peer discovery unavailable."
            )
        try:
            result = self.provider.suggest_peers(
                entity, company_name or entity, sector or "", industry or "",
                max_peers=max_peers,
            )
        except ProviderUnavailableError as exc:
            logger.warning("Peer research unavailable for %s: %s", entity, exc.message)
            return {**self._unavailable(exc.message), "peers": []}
        except ProviderError as exc:
            return {**self._error(entity, "peers", exc.message), "peers": []}
        except Exception as exc:
            logger.exception("Unexpected peer-research failure for %s", entity)
            return {**self._error(entity, "peers", f"{type(exc).__name__}"), "peers": []}

        peers = [p for p in (result.get("peers") or []) if isinstance(p, dict) and p.get("symbol")]
        sources = result.get("sources") or []
        report_id = None
        if peers:
            try:
                report_id = self.research_repo.save_report(
                    entity,
                    "peer_discovery",
                    company_name or entity,
                    {"sector": sector, "industry": industry, "peers": peers},
                    sources=sources,
                    model=result.get("model"),
                )
                self.provenance_repo.record(
                    "research_peers",
                    entity_id=entity,
                    source_type=self.provider.name,
                    source_name=self.provider.name,
                    rows_ingested=len(peers),
                    rows_rejected=0,
                    detail=";".join(p["symbol"] for p in peers),
                )
            except Exception as exc:
                logger.warning("Peer research persist failed for %s: %s", entity, type(exc).__name__)
        logger.info("Peer research for %s: %d candidates", entity, len(peers))
        return {
            "status": DataStatus.LIVE.value if peers else DataStatus.UNAVAILABLE.value,
            "provider": self.provider.name,
            "peers": peers,
            "sources": sources,
            "report_id": report_id,
        }

    # -- news digest (labeled research, never articles) ----------------------------------

    def digest_news(self, symbol: str, company_name: str) -> dict:
        """Web-research digest of recent developments (labeled, unscored).

        Returns {"status", "items": [{title, summary, url, source,
        published_at}], "sources", "report_id"|None}. Items are RESEARCH
        EVIDENCE — never stored as NewsAPI articles, never FinBERT-scored.
        """
        entity = (symbol or "").strip().upper()
        if not getattr(self.provider, "is_configured", True):
            return self._unavailable(
                "GEMINI_API_KEY is not configured — news digest unavailable."
            )
        try:
            result = self.provider.research_news(entity, company_name or entity)
        except ProviderUnavailableError as exc:
            logger.warning("News digest unavailable for %s: %s", entity, exc.message)
            return {**self._unavailable(exc.message), "items": []}
        except ProviderError as exc:
            return {**self._error(entity, "news", exc.message), "items": []}
        except Exception as exc:
            logger.exception("Unexpected news-digest failure for %s", entity)
            return {**self._error(entity, "news", f"{type(exc).__name__}"), "items": []}

        items = [i for i in (result.get("items") or []) if isinstance(i, dict) and i.get("title")]
        sources = result.get("sources") or []
        report_id = None
        if items:
            try:
                report_id = self.research_repo.save_report(
                    entity,
                    "news_digest",
                    company_name or entity,
                    {"items": items},
                    sources=sources,
                    model=result.get("model"),
                )
                self.provenance_repo.record(
                    "research_news",
                    entity_id=entity,
                    source_type=self.provider.name,
                    source_name=self.provider.name,
                    rows_ingested=len(items),
                    rows_rejected=0,
                    detail=f"{len(items)} web-research items (labeled, unscored)",
                )
            except Exception as exc:
                logger.warning("News digest persist failed for %s: %s", entity, type(exc).__name__)
        logger.info("News digest for %s: %d items", entity, len(items))
        return {
            "status": DataStatus.LIVE.value if items else DataStatus.UNAVAILABLE.value,
            "provider": self.provider.name,
            "items": items,
            "sources": sources,
            "report_id": report_id,
        }

    # -- fundamentals enrichment (labeled web research) -----------------------------------

    FUNDAMENTALS_SOURCE_NAME = "Gemini web research (annual figures)"
    FUNDAMENTALS_RATE_LIMIT_MINUTES = 10
    FUNDAMENTALS_METRICS = (
        "total_revenue", "net_income", "total_assets",
        "total_equity", "total_debt", "operating_profit", "eps",
    )

    def enrich_fundamentals(
        self,
        symbol: str,
        company_name: str | None = None,
        *,
        financial_repo=None,
    ) -> dict:
        """Web-research enrichment of key fundamental figures.

        For inputs the structured providers cannot supply (dynamic equities
        with no stored observations). Values are WEB-RESEARCHED and stored
        with an explicit `web_research` source type so downstream consumers
        distinguish them from provider/official data — never blended into a
        score as if they carried the same reliability (the distinction
        survives to the UI via per-metric source labels and evidence).
        Cached: the latest stored report serves within the rate-limit
        window (one research per symbol per 10 minutes). Confidence-gated:
        below MIN_APPLY_CONFIDENCE the report is kept as evidence only.
        """
        entity = (symbol or "").strip().upper()
        if financial_repo is None:
            return {
                **self._unavailable(
                    "Fundamentals enrichment requires financial storage."
                ),
                "usable": False,
            }
        if not getattr(self.provider, "is_configured", True):
            return {
                **self._unavailable(
                    "GEMINI_API_KEY is not configured — fundamentals "
                    "enrichment unavailable."
                ),
                "usable": False,
            }

        # Rate limit: serve the latest stored report within the window.
        latest = self.research_repo.latest_report(entity, "fundamentals")
        if latest and latest.get("created_at"):
            try:
                age_min = (
                    datetime.now(timezone.utc)
                    - datetime.fromisoformat(str(latest["created_at"]))
                ).total_seconds() / 60.0
                if age_min < self.FUNDAMENTALS_RATE_LIMIT_MINUTES:
                    payload = latest.get("payload") or {}
                    stored_metrics = payload.get("metrics") or {}
                    if stored_metrics:
                        saved = self._store_web_fundamentals(
                            entity, stored_metrics, payload, financial_repo
                        )
                        return {
                            "status": DataStatus.CACHED.value,
                            "provider": self.provider.name,
                            "metrics_stored": saved,
                            "confidence": latest.get("confidence"),
                            "sources": latest.get("sources") or [],
                            "usable": True,
                            "report_id": latest.get("report_id"),
                            "cached": True,
                        }
                    return {
                        **self._unavailable(
                            "Web-researched fundamentals from the last run "
                            "were not usable; rate limit prevents re-running "
                            f"for {self.FUNDAMENTALS_RATE_LIMIT_MINUTES} minutes."
                        ),
                        "usable": False,
                    }
            except (TypeError, ValueError):
                pass

        try:
            result = self.provider.research_fundamentals(entity, company_name or entity)
        except ProviderUnavailableError as exc:
            logger.warning("Fundamentals research unavailable for %s: %s", entity, exc.message)
            return {**self._unavailable(exc.message), "usable": False}
        except ProviderError as exc:
            return {**self._error(entity, "fundamentals", exc.message), "usable": False}
        except Exception as exc:
            logger.exception("Unexpected fundamentals-research failure for %s", entity)
            return {**self._error(entity, "fundamentals", f"{type(exc).__name__}"), "usable": False}

        metrics = {
            m: v for m, v in (result.get("metrics") or {}).items()
            if m in self.FUNDAMENTALS_METRICS
        }
        try:
            confidence = float(result.get("confidence", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0
        sources = result.get("sources") or []
        usable = bool(metrics) and confidence >= MIN_APPLY_CONFIDENCE

        payload = {
            "metrics": metrics,
            "fiscal_year": result.get("fiscal_year"),
            "currency": result.get("currency"),
            "usable": usable,
        }
        report_id = None
        try:
            report_id = self.research_repo.save_report(
                entity,
                "fundamentals",
                company_name or entity,
                payload,
                confidence=confidence,
                sources=sources,
                model=result.get("model"),
            )
            self.provenance_repo.record(
                "research_fundamentals",
                entity_id=entity,
                source_type=self.provider.name,
                source_name=self.FUNDAMENTALS_SOURCE_NAME,
                rows_ingested=len(metrics) if usable else 0,
                rows_rejected=0,
                detail=f"fiscal_year={result.get('fiscal_year')}; usable={usable}",
            )
        except Exception as exc:
            logger.warning("Fundamentals research persist failed: %s", type(exc).__name__)

        stored = 0
        if usable:
            stored = self._store_web_fundamentals(entity, metrics, payload, financial_repo)
        logger.info(
            "Fundamentals research for %s: %d metrics, usable=%s, stored=%s",
            entity, len(metrics), usable, stored,
        )
        return {
            "status": DataStatus.LIVE.value if usable else DataStatus.UNAVAILABLE.value,
            "provider": self.provider.name,
            "metrics_stored": stored,
            "confidence": confidence,
            "sources": sources,
            "usable": usable,
            "report_id": report_id,
            "cached": False,
        }

    def _store_web_fundamentals(
        self, entity: str, metrics: dict, payload: dict, financial_repo
    ) -> int:
        """Store web-researched figures as labeled observations (never official)."""
        from datetime import date as _date

        from app.domain.models.financial import (
            ConsolidationBasis,
            FinancialObservation,
            StatementType,
        )

        fiscal_year = str(payload.get("fiscal_year") or "").strip()
        period_end = None
        for suffix in ("FY", "fy"):
            if fiscal_year.startswith(suffix) and fiscal_year[len(suffix):].isdigit():
                period_end = _date(int(fiscal_year[len(suffix):]), 3, 31)
                break
        currency = str(payload.get("currency") or "INR").strip() or "INR"
        content_hash = hashlib.sha256(
            repr(sorted(metrics.items())).encode("utf-8")
        ).hexdigest()
        source_name = self.FUNDAMENTALS_SOURCE_NAME + (
            f" ({fiscal_year})" if fiscal_year else ""
        )
        observations: list = []
        for metric, value in metrics.items():
            observations.append(
                FinancialObservation(
                    entity_id=entity,
                    metric=metric,
                    value=value,
                    unit="ratio" if metric == "eps" else "INR",
                    currency=currency,
                    period_start=period_end - timedelta(days=365) if period_end else None,
                    period_end=period_end,
                    statement_type=(
                        StatementType.INCOME_STATEMENT
                        if metric in ("total_revenue", "net_income", "operating_profit", "eps")
                        else StatementType.BALANCE_SHEET
                    ),
                    consolidation_basis=ConsolidationBasis.UNKNOWN,
                    fiscal_year=fiscal_year or None,
                    source_type="web_research",
                    source_name=source_name,
                    source_reference="web research (see research reports)",
                    content_hash=content_hash,
                )
            )
        # Replace the previous web-research snapshot (scoped by source type);
        # official filings and legacy imports are never touched.
        replaced = financial_repo.delete_observations(entity, "web_research")
        saved = financial_repo.save_observations(observations) if observations else 0
        return saved
