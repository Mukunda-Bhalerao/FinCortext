"""Public market-news RSS feeds. Only headline, link, publisher and time are kept."""

import asyncio
import calendar
import logging
from datetime import UTC, datetime

import feedparser
import httpx

from app.schemas.market import NewsItem

log = logging.getLogger(__name__)

FEEDS = {
    "The Economic Times": "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
    "Business Standard": "https://www.business-standard.com/rss/markets-106.rss",
    "Mint": "https://www.livemint.com/rss/markets",
}
_HEADERS = {"User-Agent": "Mozilla/5.0 (FinCortext research client)"}


def parse_feed(publisher: str, content: bytes) -> list[NewsItem]:
    parsed = feedparser.parse(content)
    items = []
    for entry in parsed.entries:
        title = (entry.get("title") or "").strip()
        link = (entry.get("link") or "").strip()
        if not title or not link.startswith(("https://", "http://")):
            continue
        stamp = entry.get("published_parsed") or entry.get("updated_parsed")
        published = datetime.fromtimestamp(calendar.timegm(stamp), tz=UTC) if stamp else None
        items.append(NewsItem(title=title, link=link, publisher=publisher, published_at=published))
    return items


async def fetch_all() -> tuple[list[NewsItem], list[str], list[str]]:
    """Returns (items, publishers fetched, publishers that failed)."""
    async with httpx.AsyncClient(timeout=10.0, headers=_HEADERS, follow_redirects=True) as client:

        async def one(publisher: str, url: str) -> list[NewsItem] | None:
            try:
                resp = await client.get(url)
                resp.raise_for_status()
                return parse_feed(publisher, resp.content)
            except (httpx.HTTPError, ValueError) as exc:
                log.warning("news feed %s failed: %s", publisher, type(exc).__name__)
                return None

        results = await asyncio.gather(*(one(p, u) for p, u in FEEDS.items()))
    items: list[NewsItem] = []
    ok, failed = [], []
    for publisher, result in zip(FEEDS, results, strict=True):
        if result is None:
            failed.append(publisher)
        else:
            ok.append(publisher)
            items.extend(result)
    return items, ok, failed
