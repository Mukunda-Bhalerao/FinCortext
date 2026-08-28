"""News service: provider → entity association → dedup → storage → provenance.

Orchestration layer used by API routes and the Sentiment Agent. Business
logic lives here, not in route handlers.

Graceful degradation contract:
- Missing NEWS_API_KEY  -> refresh returns status UNAVAILABLE (no raise);
  stored articles remain readable; all unrelated modules keep working.
- Provider/rate/network failure -> status ERROR with the provider message.
- The service never fabricates articles and never silently substitutes
  sample data for live news.
"""

from __future__ import annotations

from datetime import date, timedelta

from app.core.config import Settings, settings
from app.core.exceptions import ProviderError, ProviderUnavailableError
from app.core.logging import get_logger
from app.data.universe.universe_config import get_universe_entry
from app.domain.contracts.providers import NewsProvider
from app.domain.models.base import DataStatus
from app.domain.models.news import NewsArticle
from app.repositories.news_repository import NewsRepository
from app.repositories.provenance_repository import ProvenanceRepository

logger = get_logger("services.news")

DEFAULT_LOOKBACK_DAYS = 7


class NewsService:
    def __init__(
        self,
        provider: NewsProvider,
        news_repo: NewsRepository,
        provenance_repo: ProvenanceRepository,
        config: Settings | None = None,
    ):
        self.provider = provider
        self.news_repo = news_repo
        self.provenance_repo = provenance_repo
        self.config = config or settings

    # -- status ------------------------------------------------------------------

    def get_status(self) -> dict:
        """Provider configuration status (safe for health/UI display)."""
        configured = getattr(self.provider, "is_configured", True)
        return {
            "provider": self.provider.name,
            "configured": configured,
            "status": (
                DataStatus.LIVE.value if configured else DataStatus.UNAVAILABLE.value
            ),
            "message": (
                None
                if configured
                else "NEWS_API_KEY is not configured — live news retrieval is "
                "unavailable. Stored/sample news can still be used where "
                "explicitly selected."
            ),
        }

    # -- refresh (live retrieval) ---------------------------------------------------

    def refresh_entity_news(
        self,
        symbol: str,
        query: str | None = None,
        days: int = DEFAULT_LOOKBACK_DAYS,
        page_size: int = 50,
    ) -> dict:
        """Fetch live news for a universe entity and store it (deduplicated).

        Never raises for provider problems — returns an explicit status dict
        so unrelated modules and the API stay functional.
        """
        entry = get_universe_entry(symbol)

        if not getattr(self.provider, "is_configured", True):
            return {
                "symbol": entry.symbol,
                "status": DataStatus.UNAVAILABLE.value,
                "fetched": 0,
                "stored": 0,
                "duplicates": 0,
                "provider": self.provider.name,
                "message": "NEWS_API_KEY is not configured — live news "
                "retrieval unavailable.",
            }

        effective_query = query or f'"{entry.name}" OR {entry.symbol}'
        to_date = date.today()
        from_date = to_date - timedelta(days=max(1, int(days)))

        try:
            articles = self.provider.fetch_articles(
                effective_query,
                from_date=from_date.isoformat(),
                to_date=to_date.isoformat(),
                page_size=page_size,
            )
        except ProviderUnavailableError as exc:
            logger.warning("News refresh unavailable for %s: %s", entry.symbol, exc.message)
            return {
                "symbol": entry.symbol,
                "status": DataStatus.UNAVAILABLE.value,
                "fetched": 0,
                "stored": 0,
                "duplicates": 0,
                "provider": self.provider.name,
                "message": exc.message,
            }
        except ProviderError as exc:
            return self._provider_error_result(entry.symbol, exc.message)
        except Exception as exc:  # any provider crash → explicit ERROR, never propagate
            logger.exception("Unexpected news provider failure for %s", entry.symbol)
            return self._provider_error_result(entry.symbol, f"{type(exc).__name__}: {exc}")

        stored = self.store_articles(articles, entity_id=entry.symbol)
        return {
            "symbol": entry.symbol,
            "status": DataStatus.LIVE.value if stored["stored"] else DataStatus.CACHED.value,
            "fetched": stored["fetched"],
            "stored": stored["stored"],
            "duplicates": stored["duplicates"],
            "provider": self.provider.name,
            "query": effective_query,
            "from_date": from_date.isoformat(),
            "to_date": to_date.isoformat(),
        }

    def _provider_error_result(self, symbol: str, message: str) -> dict:
        """Uniform ERROR result for provider failures (recorded in provenance)."""
        logger.error("News refresh failed for %s: %s", symbol, message)
        self.provenance_repo.record(
            "news_refresh_failed",
            entity_id=symbol,
            source_type=self.provider.name,
            source_name=self.provider.name,
            rows_ingested=0,
            rows_rejected=0,
            detail=message,
        )
        return {
            "symbol": symbol,
            "status": DataStatus.ERROR.value,
            "fetched": 0,
            "stored": 0,
            "duplicates": 0,
            "provider": self.provider.name,
            "message": message,
        }

    # -- storage -----------------------------------------------------------------

    def store_articles(self, articles: list[NewsArticle], entity_id: str) -> dict:
        """Associate articles with an entity and persist them (dedup by id)."""
        associated: list[NewsArticle] = []
        for a in articles:
            associated.append(a.model_copy(update={"entity_id": entity_id.upper()}))
        stored = self.news_repo.save_articles(associated)
        duplicates = len(associated) - stored
        if associated:
            self.provenance_repo.record(
                "news_ingest",
                entity_id=entity_id.upper(),
                source_type=self.provider.name,
                source_name=self.provider.name,
                rows_ingested=stored,
                rows_rejected=0,
                detail=f"{len(associated)} fetched, {duplicates} duplicates skipped",
            )
        logger.info(
            "News stored for %s: %d new, %d duplicates",
            entity_id, stored, duplicates,
        )
        return {"fetched": len(associated), "stored": stored, "duplicates": duplicates}

    # -- retrieval -----------------------------------------------------------------

    def get_entity_news(self, symbol: str, limit: int = 50) -> dict:
        """Stored articles for an entity with explicit CACHED/UNAVAILABLE status."""
        entry = get_universe_entry(symbol)
        articles = self.news_repo.get_articles(entry.symbol, limit=limit)
        return {
            "symbol": entry.symbol,
            "name": entry.name,
            "status": (
                DataStatus.CACHED.value if articles else DataStatus.UNAVAILABLE.value
            ),
            "count": len(articles),
            "provider_configured": getattr(self.provider, "is_configured", True),
            "articles": [
                {
                    "article_id": a.article_id,
                    "title": a.title,
                    "description": a.description,
                    "source": a.source,
                    "source_url": a.source_url,
                    "published_at": a.published_at.isoformat() if a.published_at else None,
                    "collected_at": a.collected_at.isoformat(),
                    "language": a.language,
                    "content_hash": a.content_hash,
                    "source_type": a.source_type.value,
                    "source_name": a.source_name,
                }
                for a in articles
            ],
        }