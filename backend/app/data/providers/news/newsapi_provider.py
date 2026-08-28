"""NewsAPI adapter implementing the NewsProvider contract.

Translates NewsAPI (newsapi.org) `/v2/everything` responses into canonical
NewsArticle models at the boundary. The API key is supplied ONLY via
configuration (constructor receives it from Settings; Settings reads the
NEWS_API_KEY environment variable) — never hardcoded.

Failure handling (never fabricates articles):
- missing/empty key          -> ProviderUnavailableError
- HTTP 401/403 (bad key)     -> ProviderUnavailableError
- HTTP 429 (rate limit)      -> ProviderError (rate-limited)
- other HTTP / network error -> ProviderError
- API-level error payload    -> ProviderError

Duplicate detection: `article_id` is a stable SHA-256 of the canonical
article URL (falls back to title+published hash when URL is missing), so the
same story re-fetched later maps to the same id and is deduplicated in
storage. `content_hash` (SHA-256 of title|description|content) is stored for
audit/dedup support.
"""

from __future__ import annotations

import hashlib
from datetime import datetime

import requests

from app.core.exceptions import ProviderError, ProviderUnavailableError
from app.core.logging import get_logger
from app.domain.contracts.providers import NewsProvider
from app.domain.models.base import DataSourceType
from app.domain.models.news import NewsArticle

logger = get_logger("providers.newsapi")

NEWSAPI_BASE_URL = "https://newsapi.org/v2/everything"
REQUEST_TIMEOUT_SECONDS = 20


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def parse_published_at(raw: str | None) -> datetime | None:
    """Parse NewsAPI ISO-8601 timestamps ('...Z' or with offset). None on failure."""
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


class NewsAPINewsProvider(NewsProvider):
    """NewsAPI adapter. Replaceable by any future NewsProvider implementation."""

    name = "newsapi"

    def __init__(self, api_key: str | None):
        # Key comes exclusively from configuration (NEWS_API_KEY env var).
        self._api_key = (api_key or "").strip()

    @property
    def is_configured(self) -> bool:
        return bool(self._api_key)

    # -- NewsProvider contract -------------------------------------------------

    def fetch_articles(
        self,
        query: str,
        from_date: str | None = None,
        to_date: str | None = None,
        page_size: int = 50,
    ) -> list[NewsArticle]:
        if not self.is_configured:
            raise ProviderUnavailableError(
                "NEWS_API_KEY is not configured — live news retrieval is "
                "unavailable. Set NEWS_API_KEY in the environment/.env to "
                "enable it.",
                details={"provider": self.name},
            )
        if not query or not query.strip():
            raise ProviderError(
                "News query must be a non-empty string.",
                details={"provider": self.name},
            )

        params = {
            "q": query,
            "pageSize": max(1, min(int(page_size), 100)),
            "language": "en",
            "sortBy": "publishedAt",
        }
        if from_date:
            params["from"] = from_date
        if to_date:
            params["to"] = to_date

        try:
            response = requests.get(
                NEWSAPI_BASE_URL,
                params=params,
                headers={"X-Api-Key": self._api_key},
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
        except requests.RequestException as exc:
            raise ProviderError(
                f"NewsAPI request failed: {exc}",
                details={"provider": self.name, "query": query},
            ) from exc

        if response.status_code in (401, 403):
            raise ProviderUnavailableError(
                "NewsAPI rejected the configured key (HTTP "
                f"{response.status_code}) — live news retrieval is unavailable.",
                details={"provider": self.name},
            )
        if response.status_code == 429:
            raise ProviderError(
                "NewsAPI rate limit reached (HTTP 429). Retry later.",
                details={"provider": self.name},
            )
        if response.status_code != 200:
            raise ProviderError(
                f"NewsAPI returned HTTP {response.status_code}.",
                details={"provider": self.name},
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise ProviderError(
                "NewsAPI returned a non-JSON response.",
                details={"provider": self.name},
            ) from exc

        if payload.get("status") == "error":
            raise ProviderError(
                f"NewsAPI error: {payload.get('message', 'unknown error')}",
                details={"provider": self.name, "code": payload.get("code")},
            )

        articles: list[NewsArticle] = []
        for raw in payload.get("articles", []):
            article = self.normalize_article(raw)
            if article is not None:
                articles.append(article)
        return articles

    # -- normalization -----------------------------------------------------------

    @staticmethod
    def normalize_article(raw: dict) -> NewsArticle | None:
        """Convert one NewsAPI article payload to the canonical model.

        Returns None for unusable entries (no title) — never raises for a
        single malformed article; malformed entries are skipped visibly in
        logs by the caller if needed.
        """
        title = (raw.get("title") or "").strip()
        if not title:
            return None

        source_url = (raw.get("url") or "").strip() or None
        description = (raw.get("description") or "").strip() or None
        content = (raw.get("content") or "").strip() or None
        published_at = parse_published_at(raw.get("publishedAt"))

        # Stable identity: URL hash when available, else title+timestamp hash.
        if source_url:
            article_id = _sha256(source_url)
        else:
            article_id = _sha256(
                f"{title}|{raw.get('publishedAt') or ''}"
            )
        content_hash = _sha256(
            f"{title}|{description or ''}|{content or ''}"
        )

        source_raw = raw.get("source") or {}
        source_name = (source_raw.get("name") or "").strip() or None

        return NewsArticle(
            article_id=article_id,
            title=title,
            description=description,
            content=content,
            source=source_name,
            source_url=source_url,
            published_at=published_at,
            language=(raw.get("language") or "").strip() or None,
            entity_id=None,  # associated by the service layer, not the provider
            content_hash=content_hash,
            source_type=DataSourceType.NEWS_API,
            source_name=NewsAPINewsProvider.name,
        )