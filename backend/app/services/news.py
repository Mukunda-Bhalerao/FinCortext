"""Market headlines from public RSS feeds, cached in DuckDB."""

from datetime import UTC, datetime, timedelta

from app.db import Database
from app.providers import rss
from app.schemas.market import NewsFeed, NewsItem

CACHE_KEY = "news:markets"
TTL = timedelta(minutes=10)
MAX_ITEMS = 40


class NewsService:
    def __init__(self, db: Database, enabled: bool):
        self._db = db
        self._enabled = enabled

    async def latest(self) -> NewsFeed:
        if not self._enabled:
            return NewsFeed(
                items=[], sources_ok=[], sources_failed=[], fetched_at=datetime.now(UTC)
            )
        hit = self._db.cache_get(CACHE_KEY)
        if hit is not None:
            return NewsFeed.model_validate(hit[0])
        items, ok, failed = await rss.fetch_all()
        seen: set[str] = set()
        unique: list[NewsItem] = []
        for item in items:
            marker = item.title.casefold()
            if marker not in seen:
                seen.add(marker)
                unique.append(item)
        floor = datetime.min.replace(tzinfo=UTC)
        unique.sort(key=lambda i: i.published_at or floor, reverse=True)
        feed = NewsFeed(
            items=unique[:MAX_ITEMS],
            sources_ok=ok,
            sources_failed=failed,
            fetched_at=datetime.now(UTC),
        )
        if ok:
            self._db.cache_put(CACHE_KEY, "rss", feed.model_dump(mode="json"), TTL)
        return feed
