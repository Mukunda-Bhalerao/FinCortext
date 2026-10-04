"""Company data preparation: the single SEARCH -> PREPARE -> STORE -> AGENTS flow.

When a user selects a stock (static universe or dynamic Upstox equity), this
service prepares everything the existing analysts consume, through the same
repositories they already read:

1. Resolve the company through Upstox (static entries win; valid NSE equities
   are registered dynamically — the static universe never blocks selection).
2. Enrich company metadata: sector/industry from structured data when known,
   else grounded Gemini web research (stored with sources, never fabricated).
3. Fetch + store the current Upstox quote snapshot (source timestamp kept).
4. Fetch + store historical OHLCV (existing validation/storage pipeline).
5. Refresh provider fundamentals for the Firm Analyst (existing service).
6. Refresh news for the Sentiment Analyst (NewsAPI with company-name query
   variants; Gemini digest as labeled research fallback, never articles).
7. Ensure Industry Analyst peer coverage: configured sector/industry peers
   first, then curated candidates + official NSE-industry peers, then
   Gemini-suggested peers — every candidate validated live via Upstox
   (exact listing match), never invented.

No agent fetches independently — agents keep reading repositories only.
Nothing is fabricated: genuinely missing data stays UNAVAILABLE/ERROR with an
explicit reason, per-area statuses roll up into an overall readiness of
`ready` / `partial` / `unavailable`, and a component-level `components` block
(market/fundamentals/company_metadata/industry/peers/news/web_research)
reports READY/PARTIAL/UNAVAILABLE per consumer.
"""

from __future__ import annotations

from app.agents.industry.methodology import MIN_PRICES_FOR_METRICS
from app.core.exceptions import NotFoundError, ProviderError, ProviderUnavailableError
from app.core.logging import get_logger
from app.data.universe.universe_config import (
    get_industry_peers,
    get_sector_peer_candidates,
    get_sector_peers,
    get_universe_entry,
    register_dynamic_entry,
)
from app.domain.models.base import DataStatus

logger = get_logger("services.company_preparation")

# Industry factors need a peer median: aim for at least this many peers with
# usable price history before falling back to dynamic discovery.
MIN_USABLE_PEERS = 2

# Upper bound on discovered peers kept per company (relevance-ordered).
MAX_DISCOVERED_PEERS = 4


def _ready(status: str | None) -> bool:
    return status in (DataStatus.LIVE.value, DataStatus.CACHED.value)


class CompanyPreparationService:
    """Orchestrates per-company data readiness for all downstream agents."""

    def __init__(
        self,
        *,
        market_service,
        fundamentals_service,
        news_service,
        market_repo,
        financial_repo,
        news_repo,
        instrument_repo=None,
        universe_repo=None,
        research_service=None,
        industry_classifier=None,
    ):
        self.market_service = market_service
        self.fundamentals_service = fundamentals_service
        self.news_service = news_service
        self.market_repo = market_repo
        self.financial_repo = financial_repo
        self.news_repo = news_repo
        self.instrument_repo = instrument_repo
        self.universe_repo = universe_repo
        self.research_service = research_service
        if industry_classifier is None:
            from app.data.universe.industry_classifier import IndustryClassifier

            industry_classifier = IndustryClassifier()
        self.industry_classifier = industry_classifier
        # Research usage observed during one prepare run (kind -> outcome).
        # Reset per prepare_company call; surfaced in the web_research area.
        self._research_events: list[dict] = []

    # -- public flow -----------------------------------------------------------

    def prepare_company(self, symbol: str, instrument_key: str | None = None) -> dict:
        """Run the full preparation flow for one company. Never raises for
        provider problems — each area reports its own honest status."""
        self._research_events = []
        resolved = self.market_service.resolve_symbol(symbol, instrument_key)
        canonical = resolved["symbol"]
        areas: dict[str, dict] = {}

        areas["resolve"] = {
            "status": DataStatus.LIVE.value,
            "symbol": canonical,
            "name": resolved["name"],
            "instrument_key": resolved.get("instrument_key"),
            "dynamic": resolved.get("dynamic", False),
        }

        # Metadata enrichment first: peers/news downstream depend on the
        # (possibly enriched) sector and company name.
        entry, areas["company_metadata"] = self._enrich_metadata(canonical)
        if entry is None:  # unreachable post-resolve; stay honest if hit
            entry = get_universe_entry(canonical)
        areas["quote"] = self._prepare_quote(canonical, resolved.get("instrument_key"))
        areas["history"] = self._prepare_history(canonical, resolved.get("instrument_key"))
        areas["fundamentals"] = self._prepare_fundamentals(canonical)
        areas["news"] = self._prepare_news(entry)
        areas["peers"] = self._prepare_peers(entry)
        areas["web_research"] = self._web_research_area()

        readiness = self._overall_readiness(areas)
        return {
            "symbol": canonical,
            "name": entry.name,
            "instrument_key": resolved.get("instrument_key"),
            "sector": entry.sector,
            "industry": entry.industry,
            "readiness": readiness,
            "areas": areas,
            "components": self._component_readiness(areas),
        }

    def readiness(self, symbol: str) -> dict:
        """Readiness from stored data only (no network calls)."""
        try:
            entry = get_universe_entry(symbol)
        except NotFoundError as exc:
            return {
                "symbol": (symbol or "").strip().upper(),
                "readiness": DataStatus.UNAVAILABLE.value,
                "reason": exc.message,
                "areas": {},
            }
        canonical = entry.symbol
        quote = self.market_repo.get_stored_quote(canonical)
        price_rows = self.market_repo.count(canonical)
        latest = self.market_repo.latest_trade_date(canonical)
        fund_rows = len(self.financial_repo.get_observations(canonical))
        news_rows = len(self.news_repo.get_articles(canonical, limit=1000))
        peers = [p.symbol for p in get_sector_peers(canonical) if p.symbol != canonical]
        peers_with_data = [
            p for p in peers if self.market_repo.count(p) >= MIN_PRICES_FOR_METRICS
        ]
        metadata_known = (
            entry.sector not in {"Unknown", "Dynamic"}
            and entry.industry not in {"Unknown", "Dynamic"}
        )
        research_count = 0
        try:
            if self.research_service is not None:
                research_count = self.research_service.research_repo.count(canonical)
        except Exception:
            research_count = 0
        areas = {
            "quote": {
                "status": DataStatus.LIVE.value if quote and quote.get("last_price") is not None else DataStatus.UNAVAILABLE.value,
                "timestamp": (quote or {}).get("timestamp"),
                "source": (quote or {}).get("source"),
            },
            "history": {
                "status": DataStatus.LIVE.value if price_rows >= MIN_PRICES_FOR_METRICS else (
                    DataStatus.CACHED.value if price_rows else DataStatus.UNAVAILABLE.value
                ),
                "rows": price_rows,
                "latest_trade_date": latest.isoformat() if latest else None,
            },
            "fundamentals": {
                "status": DataStatus.CACHED.value if fund_rows else DataStatus.UNAVAILABLE.value,
                "observations": fund_rows,
            },
            "company_metadata": {
                "status": DataStatus.LIVE.value if metadata_known else DataStatus.UNAVAILABLE.value,
                "sector": entry.sector,
                "industry": entry.industry,
            },
            "news": {
                "status": DataStatus.CACHED.value if news_rows else DataStatus.UNAVAILABLE.value,
                "articles": news_rows,
                "stored_total": news_rows,
            },
            "peers": {
                "status": DataStatus.CACHED.value if peers_with_data else DataStatus.UNAVAILABLE.value,
                "peers": peers,
                "peers_with_data": peers_with_data,
                "usable_peers": peers_with_data,
            },
            "web_research": {
                "status": DataStatus.CACHED.value if research_count else DataStatus.UNAVAILABLE.value,
                "reports": research_count,
            },
        }
        return {
            "symbol": canonical,
            "name": entry.name,
            "sector": entry.sector,
            "industry": entry.industry,
            "readiness": self._overall_readiness(areas),
            "areas": areas,
            "components": self._component_readiness(areas),
        }

    def company_peers(self, symbol: str) -> dict:
        """Effective peer set for a company (configured + discovered)."""
        entry = get_universe_entry(symbol)  # raises NotFoundError -> 404
        peers = [p for p in get_sector_peers(entry.symbol) if p.symbol != entry.symbol]
        industry = [p for p in get_industry_peers(entry.symbol) if p.symbol != entry.symbol]
        industry_only = [p for p in industry if p.symbol not in {q.symbol for q in peers}]
        rows = []
        for p in peers + industry_only:
            latest = self.market_repo.latest_trade_date(p.symbol)
            rows.append(
                {
                    "symbol": p.symbol,
                    "name": p.name,
                    "sector": p.sector,
                    "industry": p.industry,
                    "relation": "sector" if p in peers else "industry",
                    "rows": self.market_repo.count(p.symbol),
                    "latest_trade_date": latest.isoformat() if latest else None,
                }
            )
        return {
            "symbol": entry.symbol,
            "sector": entry.sector,
            "industry": entry.industry,
            "count": len(rows),
            "peers": rows,
        }

    # -- per-area steps (each isolated; provider failures become statuses) -----

    def _enrich_metadata(self, symbol: str):
        """Resolve sector/industry: structured data first, Gemini research fallback.

        Order for ANY symbol: configured universe entry → official NSE Nifty
        500 list → Gemini research (only if wired) → honestly Unknown.
        Returns (entry, area). A dynamically selected company must not remain
        "Unknown" when structured sources can classify it — research is
        applied only when usable (sector+industry present, confidence
        threshold met), and the Upstox company name is kept canonical
        (research never renames).
        """
        try:
            entry = get_universe_entry(symbol)
        except NotFoundError as exc:
            return None, {"status": DataStatus.UNAVAILABLE.value, "error": exc.message}
        if entry.sector not in {"Unknown", "Dynamic"} and entry.industry not in {"Unknown", "Dynamic"}:
            return entry, {
                "status": DataStatus.LIVE.value,
                "source": "universe",
                "sector": entry.sector,
                "industry": entry.industry,
            }
        # Structured classification (no Gemini dependency): the official NSE
        # Nifty 500 industry list.
        structured = self._classify_structured(entry)
        if structured is not None:
            return structured
        if self.research_service is None:
            return entry, {
                "status": DataStatus.UNAVAILABLE.value,
                "sector": entry.sector,
                "industry": entry.industry,
                "reason": "Sector/industry unknown and no research service is wired.",
            }
        try:
            outcome = self.research_service.enrich_company(entry.symbol, entry.name)
        except Exception as exc:  # research must never break preparation
            logger.exception("Metadata enrichment failed for %s", entry.symbol)
            self._research_events.append({"kind": "company_profile", "status": DataStatus.ERROR.value})
            return entry, {
                "status": DataStatus.ERROR.value,
                "sector": entry.sector,
                "industry": entry.industry,
                "error": f"{type(exc).__name__}",
            }
        self._research_events.append(
            {"kind": "company_profile", "status": outcome.get("status", DataStatus.UNAVAILABLE.value)}
        )
        if not outcome.get("usable"):
            return entry, {
                "status": DataStatus.UNAVAILABLE.value,
                "sector": entry.sector,
                "industry": entry.industry,
                "reason": outcome.get("message") or (
                    "Web research could not confidently classify this company; "
                    "sector/industry remain unknown."
                ),
                "sources": outcome.get("sources") or [],
            }
        try:
            updated = entry.model_copy(
                update={"sector": outcome["sector"], "industry": outcome["industry"]}
            )
            register_dynamic_entry(updated)
            if self.universe_repo is not None:
                self.universe_repo.upsert_entry(updated)
            entry = updated
        except Exception as exc:
            logger.warning("Enriched metadata persist failed for %s: %s", symbol, type(exc).__name__)
        return entry, {
            "status": DataStatus.LIVE.value,
            "source": "gemini_research",
            "sector": entry.sector,
            "industry": entry.industry,
            "confidence": outcome.get("confidence"),
            "business_description": outcome.get("business_description"),
            "sources": outcome.get("sources") or [],
            "report_id": outcome.get("report_id"),
        }

    def _classify_structured(self, entry):
        """Apply the official NSE-CSV classification to an Unknown entry.

        Returns (updated_entry, area) on success, None to fall through to
        Gemini research. Structured sources need no quota and carry no
        confidence-gating beyond presence of both fields.
        """
        classifier = getattr(self, "industry_classifier", None)
        if classifier is None:
            return None
        isin = getattr(entry, "isin", None)
        if not isin and self.instrument_repo is not None:
            try:
                cached = self.instrument_repo.get_by_symbol(entry.symbol)
                isin = (cached or {}).get("isin")
            except Exception:
                pass
        try:
            result = classifier.classify(
                entry.symbol,
                company_name=entry.name,
                isin=isin,
            )
        except Exception as exc:
            logger.warning(
                "Structured classification failed for %s: %s", entry.symbol, type(exc).__name__
            )
            return None
        if result is None or not result.sector or not result.industry:
            return None
        try:
            updated = entry.model_copy(
                update={"sector": result.sector, "industry": result.industry}
            )
            register_dynamic_entry(updated)
            if self.universe_repo is not None:
                self.universe_repo.upsert_entry(updated)
            entry = updated
        except Exception as exc:
            logger.warning(
                "Classified metadata persist failed for %s: %s", entry.symbol, type(exc).__name__
            )
        report_id = None
        if self.research_service is not None:
            try:
                report_id = self.research_service.record_classification(
                    entry.symbol,
                    sector=result.sector,
                    industry=result.industry,
                    company_name=entry.name,
                    source=result.source,
                    confidence=result.confidence,
                    isin=result.isin,
                )
            except Exception:
                pass
        logger.info(
            "Classified %s via %s: sector=%s industry=%s",
            entry.symbol, result.source, result.sector, result.industry,
        )
        return entry, {
            "status": DataStatus.LIVE.value,
            "source": result.source,
            "sector": entry.sector,
            "industry": entry.industry,
            "confidence": result.confidence,
            "report_id": report_id,
        }

    def _prepare_quote(self, symbol: str, instrument_key: str | None) -> dict:
        try:
            quote = self.market_service.get_quote(symbol, instrument_key)
        except (ProviderError, ProviderUnavailableError) as exc:
            stored = self.market_repo.get_stored_quote(symbol)
            if stored and stored.get("last_price") is not None:
                return {
                    "status": DataStatus.CACHED.value,
                    "note": f"Live quote unavailable ({type(exc).__name__}); showing last stored snapshot.",
                    "timestamp": stored.get("timestamp"),
                    "source": stored.get("source"),
                }
            return {"status": DataStatus.UNAVAILABLE.value, "error": exc.message}
        except NotFoundError as exc:
            return {"status": DataStatus.UNAVAILABLE.value, "error": exc.message}
        # get_quote persists the live snapshot; confirm what is stored so the
        # reported timestamp is exactly what downstream reads will see.
        stored = self.market_repo.get_stored_quote(symbol)
        return {
            "status": quote.get("status", DataStatus.LIVE.value),
            "source": quote.get("source"),
            "timestamp": (stored or {}).get("timestamp") or quote.get("timestamp"),
            "last_price": quote.get("last_price"),
        }

    def _prepare_history(self, symbol: str, instrument_key: str | None) -> dict:
        rows = self.market_repo.count(symbol)
        latest = self.market_repo.latest_trade_date(symbol)
        if rows >= MIN_PRICES_FOR_METRICS and latest is not None:
            from datetime import date as _date

            if (_date.today() - latest).days <= 7:
                return {
                    "status": DataStatus.CACHED.value,
                    "action": "cached",
                    "rows": rows,
                    "latest_trade_date": latest.isoformat(),
                }
        try:
            outcome = self.market_service.refresh_symbol(symbol, instrument_key=instrument_key)
        except (ProviderError, ProviderUnavailableError) as exc:
            if rows:
                return {
                    "status": DataStatus.CACHED.value,
                    "action": "refresh_failed",
                    "rows": rows,
                    "error": exc.message,
                }
            return {"status": DataStatus.ERROR.value, "action": "refresh_failed", "error": exc.message}
        latest = self.market_repo.latest_trade_date(symbol)
        return {
            "status": outcome.get("status", DataStatus.UNAVAILABLE.value),
            "action": "refreshed",
            "rows_stored": outcome.get("rows_stored", 0),
            "rows": self.market_repo.count(symbol),
            "provider": outcome.get("provider"),
            "latest_trade_date": latest.isoformat() if latest else None,
        }

    def _prepare_fundamentals(self, symbol: str) -> dict:
        try:
            outcome = self.fundamentals_service.refresh_symbol(symbol)
        except (ProviderError, ProviderUnavailableError) as exc:
            count = len(self.financial_repo.get_observations(symbol))
            if count:
                return {
                    "status": DataStatus.CACHED.value,
                    "observations": count,
                    "note": f"Fundamentals refresh failed ({exc.message}); using stored observations.",
                }
            return {"status": DataStatus.ERROR.value, "error": exc.message}
        except Exception as exc:  # provider crash -> honest ERROR, never propagate
            logger.exception("Fundamentals preparation failed for %s", symbol)
            return {"status": DataStatus.ERROR.value, "error": f"{type(exc).__name__}: {exc}"}
        return {
            "status": outcome.get("status", DataStatus.UNAVAILABLE.value),
            "metrics": outcome.get("metrics", []),
            "observations_stored": outcome.get("observations_stored", 0),
            "warnings": outcome.get("warnings", []),
        }

    def _news_query_variants(self, entry) -> list[str]:
        """Retrieval query variants from the news service (provider-aware).

        NewsAPI: default OR-query, short company name, symbol/business-context
        phrasing. RSS: short|full|symbol pipe queries. Quoted full legal names
        ("ADANI POWER LTD") miss articles that say "Adani Power", so the
        short-name variant is essential for dynamic companies that carry no
        curated aliases. Retrieval only — the Sentiment Analyst's relevance
        screen enforces precision downstream.
        """
        variants = self.news_service.query_variants(entry)
        return list(variants)[:3]

    def _prepare_news(self, entry) -> dict:
        """Run the existing NewsAPI flow across company-name query variants.

        Tries variants until articles are stored (or the provider proves
        unreachable). When NewsAPI yields nothing usable, Gemini web research
        may supply a clearly labeled digest (stored as research evidence —
        never as articles, never FinBERT-scored). Distinguishes "no relevant
        articles returned by the configured provider" from "no news exists" —
        the latter is never claimed.
        """
        symbol = entry.symbol
        queries_tried: list[str] = []
        last: dict | None = None
        for variant in self._news_query_variants(entry):
            try:
                outcome = self.news_service.refresh_entity_news(symbol, query=variant)
            except Exception as exc:  # service layer already guards; stay safe
                logger.exception("News preparation failed for %s", symbol)
                last = {"status": DataStatus.ERROR.value, "error": f"{type(exc).__name__}"}
                break
            last = outcome
            queries_tried.append(outcome.get("query") or (variant or "default"))
            stored_total = len(self.news_repo.get_articles(symbol, limit=1000))
            if stored_total > 0:
                result = dict(outcome)
                result["stored_total"] = stored_total
                result["queries_tried"] = queries_tried
                return result
            if outcome.get("status") not in (DataStatus.LIVE.value, DataStatus.CACHED.value):
                break  # provider down/unconfigured — variants cannot help
        stored_total = len(self.news_repo.get_articles(symbol, limit=1000))
        result = dict(last or {"status": DataStatus.UNAVAILABLE.value})
        result["stored_total"] = stored_total
        result["queries_tried"] = queries_tried
        if stored_total == 0:
            result["note"] = (
                "No relevant articles returned by the configured provider "
                "for this company — not a claim that no news exists."
            )
            digest = self._digest_news_fallback(entry)
            if digest is not None:
                result["research"] = digest
        return result

    def _digest_news_fallback(self, entry) -> dict | None:
        """Labeled Gemini news digest when NewsAPI has nothing usable."""
        if self.research_service is None:
            return None
        try:
            outcome = self.research_service.digest_news(entry.symbol, entry.name)
        except Exception:
            logger.exception("News digest failed for %s", entry.symbol)
            self._research_events.append({"kind": "news_digest", "status": DataStatus.ERROR.value})
            return None
        self._research_events.append(
            {"kind": "news_digest", "status": outcome.get("status", DataStatus.UNAVAILABLE.value)}
        )
        if not outcome.get("items"):
            return None
        return {
            "status": outcome.get("status"),
            "items": outcome.get("items"),
            "sources": outcome.get("sources") or [],
            "report_id": outcome.get("report_id"),
            "label": (
                "Web-research digest (Gemini grounded search) — background "
                "context only, not NewsAPI articles and not FinBERT-scored."
            ),
        }

    def _prepare_peers(self, entry) -> dict:
        """Ensure usable peer history.

        Order: configured sector/industry peers → curated same-sector
        candidates + official NSE-industry peers → Gemini-suggested peers.
        Every candidate (wherever from) is validated live via Upstox with an
        exact-listing gate and gets real market history before it counts as
        usable.
        """
        symbol = entry.symbol
        if entry.sector in {"Unknown", "Dynamic"}:
            return {
                "status": DataStatus.UNAVAILABLE.value,
                "sector": entry.sector,
                "industry": entry.industry,
                "reason": (
                    "Sector is unknown for this company, so no sufficiently "
                    "relevant peer set can be assembled automatically."
                ),
                "peers": [],
                "usable_peers": [],
            }
        configured = [p for p in get_sector_peers(symbol) if p.symbol != entry.symbol]
        industry_extra = [
            p for p in get_industry_peers(symbol)
            if p.symbol != entry.symbol and p.symbol not in {q.symbol for q in configured}
        ]
        ensured = self.market_service.ensure_history(
            [p.symbol for p in configured + industry_extra],
            min_bars=MIN_PRICES_FOR_METRICS,
        )
        usable = [
            p.symbol for p in configured
            if self.market_repo.count(p.symbol) >= MIN_PRICES_FOR_METRICS
        ]
        discovered: list[dict] = []
        if len(usable) < MIN_USABLE_PEERS:
            discovered = self._discover_sector_peers(entry, usable)
            if len(usable) + len(discovered) < MIN_USABLE_PEERS:
                discovered = discovered + self._discover_peers_via_research(
                    entry, usable + [d["symbol"] for d in discovered]
                )
            if discovered:
                ensured_discovered = self.market_service.ensure_history(
                    [d["symbol"] for d in discovered],
                    min_bars=MIN_PRICES_FOR_METRICS,
                )
                ensured = ensured + ensured_discovered
                usable = [
                    d["symbol"] for d in discovered
                    if self.market_repo.count(d["symbol"]) >= MIN_PRICES_FOR_METRICS
                ] + usable
        # De-duplicate while preserving relevance order (industry-first).
        seen: set[str] = set()
        ordered_usable = [s for s in usable if not (s in seen or seen.add(s))]
        status = (
            DataStatus.LIVE.value if len(ordered_usable) >= MIN_USABLE_PEERS
            else DataStatus.CACHED.value if ordered_usable
            else DataStatus.UNAVAILABLE.value
        )
        return {
            "status": status,
            "sector": entry.sector,
            "industry": entry.industry,
            "configured_peers": [p.symbol for p in configured],
            "discovered_peers": [d["symbol"] for d in discovered],
            "discovered_sources": list({d.get("source", "curated") for d in discovered}),
            "usable_peers": ordered_usable,
            "preparation": ensured,
        }

    def _discover_peers_via_research(self, entry, already_usable: list[str]) -> list[dict]:
        """Gemini-suggested peers, each validated live via Upstox.

        Gemini identifies candidates; Upstox decides truth. Candidates pass
        through the same exact-listing gate as curated ones (fuzzy Upstox
        rows and unknown symbols are skipped, never invented). Accepted
        candidates are registered with the company's sector/industry so the
        unchanged Industry Analyst groups them as peers.
        """
        if self.research_service is None:
            return []
        try:
            outcome = self.research_service.discover_peers(
                entry.symbol, entry.name, entry.sector, entry.industry,
                max_peers=MAX_DISCOVERED_PEERS * 2,
            )
        except Exception:
            logger.exception("Research peer discovery failed for %s", entry.symbol)
            self._research_events.append({"kind": "peer_discovery", "status": DataStatus.ERROR.value})
            return []
        self._research_events.append(
            {"kind": "peer_discovery", "status": outcome.get("status", DataStatus.UNAVAILABLE.value)}
        )
        candidates = outcome.get("peers") or []
        if not candidates:
            return []
        have = set(already_usable) | {entry.symbol}
        discovered: list[dict] = []
        resolve = getattr(self.market_service, "_resolve_entry", None)
        for cand in candidates:
            cand_symbol = str((cand or {}).get("symbol") or "").strip().upper()
            if not cand_symbol or cand_symbol in have:
                continue
            if len(discovered) + len(already_usable) >= MAX_DISCOVERED_PEERS:
                break
            try:
                if resolve is not None:
                    resolved_entry = resolve(cand_symbol)
                else:
                    resolved_entry = get_universe_entry(cand_symbol)
                if resolved_entry.symbol.upper() != cand_symbol:
                    logger.info(
                        "Research peer %s skipped: Upstox resolved %s instead",
                        cand_symbol, resolved_entry.symbol,
                    )
                    continue
            except (NotFoundError, ProviderError, ProviderUnavailableError):
                logger.info("Research peer %s skipped: no live Upstox NSE equity", cand_symbol)
                continue
            except Exception:
                logger.info("Research peer %s skipped: resolution failed", cand_symbol)
                continue
            if resolved_entry.sector in {"Unknown", "Dynamic"}:
                try:
                    updated = resolved_entry.model_copy(
                        update={"sector": entry.sector, "industry": entry.industry}
                    )
                    register_dynamic_entry(updated)
                    if self.universe_repo is not None:
                        self.universe_repo.upsert_entry(updated)
                    resolved_entry = updated
                except Exception:
                    pass
            discovered.append(
                {
                    "symbol": resolved_entry.symbol,
                    "name": resolved_entry.name,
                    "sector": resolved_entry.sector,
                    "industry": resolved_entry.industry,
                    "source": "gemini",
                    "reason": (cand or {}).get("reason"),
                }
            )
            have.add(resolved_entry.symbol)
        if discovered:
            logger.info(
                "Research discovered %d peers for %s: %s",
                len(discovered), entry.symbol, [d["symbol"] for d in discovered],
            )
        return discovered

    def _discover_sector_peers(self, entry, already_usable: list[str]) -> list[dict]:
        """Validate curated + NSE-industry peer candidates live via Upstox.

        Industry matches first, then broader sector names. Each candidate is
        resolved through Upstox search (proving a real NSE listing) and
        registered with the sector/industry it was curated for. Candidates
        already usable, the company itself, or failing Upstox validation are
        skipped — never invented. Sources are tagged per peer
        ("curated" / "nifty500_csv").
        """
        have = set(already_usable) | {entry.symbol}
        candidates = get_sector_peer_candidates(entry.sector)
        # Industry-first ordering keeps relevance: same industry, then sector.
        candidates = sorted(
            candidates,
            key=lambda c: (0 if c[2] == entry.industry else 1, c[0]),
        )
        # Official NSE-industry peers supplement curated names (same shape,
        # tagged source "nifty500_csv"); industry-matched first.
        nifty: list[tuple[str, str, str]] = []
        classifier = getattr(self, "industry_classifier", None)
        if classifier is not None:
            try:
                nifty = [
                    (sym, name, entry.industry)
                    for sym, name in classifier.peers_for_industry(
                        entry.industry, exclude=have, limit=8
                    )
                ]
            except Exception as exc:
                logger.warning(
                    "NSE peer lookup failed for %s: %s", entry.symbol, type(exc).__name__
                )
        tagged: list[tuple[str, str, str, str]] = [
            (s, n, i, "curated") for s, n, i in candidates
        ] + [(s, n, i, "nifty500_csv") for s, n, i in nifty]
        tagged = sorted(
            tagged,
            key=lambda c: (0 if c[2] == entry.industry else 1, c[0]),
        )
        discovered: list[dict] = []
        resolve = getattr(self.market_service, "_resolve_entry", None)
        for cand_symbol, cand_name, cand_industry, cand_source in tagged:
            if cand_symbol in have:
                continue
            if len(discovered) + len(already_usable) >= 4:
                break
            try:
                if resolve is not None:
                    resolved_entry = resolve(cand_symbol)
                else:
                    resolved_entry = get_universe_entry(cand_symbol)
                # Exact-match gate: Upstox search is fuzzy ("LTIM" can return
                # BSE Ltd as the top row). A candidate only counts when the
                # resolved listing IS the intended company — otherwise skip.
                if resolved_entry.symbol.upper() != cand_symbol.upper():
                    logger.info(
                        "Peer candidate %s skipped: Upstox resolved %s instead (no exact listing)",
                        cand_symbol, resolved_entry.symbol,
                    )
                    continue
                meta_symbol = resolved_entry.symbol
            except (NotFoundError, ProviderError, ProviderUnavailableError):
                logger.info("Peer candidate %s skipped: no live Upstox NSE equity", cand_symbol)
                continue
            except Exception:
                logger.info("Peer candidate %s skipped: resolution failed", cand_symbol)
                continue
            # Attach the curated sector/industry when the entry lacks a known
            # one (dynamic registrations default to Unknown).
            if resolved_entry.sector in {"Unknown", "Dynamic"}:
                try:
                    updated = resolved_entry.model_copy(
                        update={"sector": entry.sector, "industry": cand_industry or entry.industry}
                    )
                    register_dynamic_entry(updated)
                    if self.universe_repo is not None:
                        self.universe_repo.upsert_entry(updated)
                    resolved_entry = updated
                except Exception:
                    pass
            discovered.append(
                {
                    "symbol": meta_symbol,
                    "name": resolved_entry.name,
                    "sector": resolved_entry.sector,
                    "industry": resolved_entry.industry,
                    "source": cand_source,
                    "reason": cand_name if cand_name != meta_symbol else None,
                }
            )
            have.add(meta_symbol)
        if discovered:
            logger.info(
                "Discovered %d sector peers for %s: %s",
                len(discovered), entry.symbol, [d["symbol"] for d in discovered],
            )
        return discovered

    def _web_research_area(self) -> dict:
        """Roll up Gemini usage observed during this run (evidence, not scores)."""
        if self.research_service is None or not getattr(
            self.research_service.provider, "is_configured", False
        ):
            return {
                "status": DataStatus.UNAVAILABLE.value,
                "reason": "Gemini web research is not configured.",
                "events": [],
            }
        if not self._research_events:
            return {
                "status": DataStatus.CACHED.value,
                "note": "No web research was needed — structured data covered everything.",
                "events": [],
            }
        usable = [
            e for e in self._research_events
            if e.get("status") == DataStatus.LIVE.value
        ]
        return {
            "status": DataStatus.LIVE.value if usable else DataStatus.UNAVAILABLE.value,
            "events": self._research_events,
            "note": (
                "Web research contributed enrichment evidence."
                if usable else
                "Web research ran but produced no usable output."
            ),
        }

    # -- rollup ------------------------------------------------------------------

    @staticmethod
    def _component_readiness(areas: dict) -> dict:
        """Consumer-level readiness per data domain: READY / PARTIAL /
        UNAVAILABLE. `areas` keeps the detailed DataStatus values; this block
        tells the frontend and agents what is actually usable."""
        quote_ok = _ready(areas.get("quote", {}).get("status"))
        history = areas.get("history", {})
        history_rows = history.get("rows", 0) or 0
        history_ok = _ready(history.get("status")) and history_rows >= MIN_PRICES_FOR_METRICS
        fund_status = areas.get("fundamentals", {}).get("status")
        meta_status = areas.get("company_metadata", {}).get("status")
        peers = areas.get("peers", {})
        usable_peers = peers.get("usable_peers") or []
        news = areas.get("news", {})
        news_stored = news.get("stored_total", 0) or 0
        web_status = areas.get("web_research", {}).get("status")

        def _level(ok: bool, partial_ok: bool) -> str:
            if ok:
                return "READY"
            if partial_ok:
                return "PARTIAL"
            return "UNAVAILABLE"

        return {
            # Current market truth needs a live quote AND usable history.
            "market": _level(
                quote_ok and history_ok,
                quote_ok or _ready(history.get("status")),
            ),
            "fundamentals": _level(
                fund_status == DataStatus.LIVE.value,
                fund_status == DataStatus.CACHED.value,
            ),
            "company_metadata": (
                "READY" if meta_status == DataStatus.LIVE.value else "UNAVAILABLE"
            ),
            # Peer-relative factors need a median: 2+ peers READY, 1 PARTIAL.
            "industry": _level(len(usable_peers) >= MIN_USABLE_PEERS, len(usable_peers) >= 1),
            "peers": _level(len(usable_peers) >= MIN_USABLE_PEERS, len(usable_peers) >= 1),
            # Sentiment needs stored articles FinBERT can score.
            "news": _level(
                news_stored > 0 and _ready(news.get("status")),
                news_stored > 0,
            ),
            "web_research": _level(
                web_status == DataStatus.LIVE.value,
                web_status == DataStatus.CACHED.value,
            ),
        }

    @staticmethod
    def _overall_readiness(areas: dict) -> str:
        """Honest rollup — `ready` ONLY when the minimum downstream data is
        actually prepared (market truth + fundamentals + known metadata +
        usable peers + usable news). Anything less is `partial`; nothing
        usable is `unavailable`. A 200 response never claims readiness the
        analysts cannot use."""
        quote_ok = areas.get("quote", {}).get("status") in (DataStatus.LIVE.value, DataStatus.CACHED.value)
        history_ok = areas.get("history", {}).get("status") in (DataStatus.LIVE.value, DataStatus.CACHED.value)
        fund_ok = areas.get("fundamentals", {}).get("status") in (DataStatus.LIVE.value, DataStatus.CACHED.value)
        metadata_ok = areas.get("company_metadata", {}).get("status") == DataStatus.LIVE.value
        peers_ok = areas.get("peers", {}).get("status") in (DataStatus.LIVE.value, DataStatus.CACHED.value)
        news_ok = areas.get("news", {}).get("status") in (DataStatus.LIVE.value, DataStatus.CACHED.value)
        if quote_ok and history_ok and fund_ok and metadata_ok and peers_ok and news_ok:
            return "ready"
        if history_ok or quote_ok or peers_ok or fund_ok or news_ok or metadata_ok:
            return "partial"
        return "unavailable"
