"""Unit tests: NewsService graceful degradation, storage, dedup, provenance."""

from datetime import datetime, timezone

import pytest

from app.data.storage.duckdb_storage import DuckDBStorage
from app.domain.contracts.providers import NewsProvider
from app.domain.models.base import DataStatus
from app.domain.models.news import NewsArticle
from app.repositories.news_repository import NewsRepository
from app.repositories.provenance_repository import ProvenanceRepository
from app.services.news_service import NewsService, default_news_query


class FixtureNewsProvider(NewsProvider):
    """Deterministic in-memory provider (no network, no key required)."""

    name = "fixture_news"

    def __init__(self, articles=None, error: Exception | None = None, configured: bool = True):
        self.articles = articles or []
        self.error = error
        self.calls = 0
        self.is_configured = configured

    def fetch_articles(self, query, from_date=None, to_date=None, page_size=50):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return list(self.articles)


def _article(url, title="TCS beats estimates", published=None):
    import hashlib

    return NewsArticle(
        article_id=hashlib.sha256(url.encode()).hexdigest(),
        title=title,
        description="Tata Consultancy Services reported growth.",
        content=None,
        source="Fixture Times",
        source_url=url,
        published_at=published or datetime(2024, 7, 15, 9, 30, tzinfo=timezone.utc),
        language="en",
        content_hash=hashlib.sha256(title.encode()).hexdigest(),
    )


@pytest.fixture()
def stack(tmp_path):
    storage = DuckDBStorage(tmp_path / "news.duckdb")
    storage.connect()
    news_repo = NewsRepository(storage)
    provenance_repo = ProvenanceRepository(storage)
    yield news_repo, provenance_repo
    storage.close()


def test_refresh_without_configured_provider_degrades(stack):
    news_repo, provenance_repo = stack
    service = NewsService(
        FixtureNewsProvider(configured=False), news_repo, provenance_repo
    )
    result = service.refresh_entity_news("TCS")
    assert result["status"] == DataStatus.UNAVAILABLE.value
    assert result["stored"] == 0
    assert "NEWS_API_KEY" in result["message"]
    # Unrelated functionality unaffected: status endpoint still works
    status = service.get_status()
    assert status["configured"] is False
    assert status["status"] == DataStatus.UNAVAILABLE.value


def test_refresh_provider_error_returns_error_status(stack):
    news_repo, provenance_repo = stack
    provider = FixtureNewsProvider(error=RuntimeError("boom"), configured=True)
    service = NewsService(provider, news_repo, provenance_repo)
    result = service.refresh_entity_news("TCS")
    assert result["status"] == DataStatus.ERROR.value
    assert "boom" in result["message"]


def test_refresh_stores_and_deduplicates(stack):
    news_repo, provenance_repo = stack
    provider = FixtureNewsProvider(articles=[_article("https://x.com/a"), _article("https://x.com/b")])
    service = NewsService(provider, news_repo, provenance_repo)

    first = service.refresh_entity_news("TCS")
    assert first["status"] == DataStatus.LIVE.value
    assert first["fetched"] == 2
    assert first["stored"] == 2

    # Second refresh with the same articles → all duplicates skipped.
    second = service.refresh_entity_news("TCS")
    assert second["stored"] == 0
    assert second["duplicates"] == 2
    assert second["status"] == DataStatus.CACHED.value

    assert news_repo.count("TCS") == 2
    # Provenance events recorded for both ingests
    events = provenance_repo.list_events(entity_id="TCS")
    assert any(e["event_type"] == "news_ingest" for e in events)


def test_get_entity_news_status(stack):
    news_repo, provenance_repo = stack
    service = NewsService(FixtureNewsProvider(), news_repo, provenance_repo)

    empty = service.get_entity_news("INFY")
    assert empty["status"] == DataStatus.UNAVAILABLE.value
    assert empty["count"] == 0

    service.store_articles([_article("https://x.com/c")], entity_id="INFY")
    stored = service.get_entity_news("INFY")
    assert stored["status"] == DataStatus.CACHED.value
    assert stored["count"] == 1
    article = stored["articles"][0]
    assert article["title"] == "TCS beats estimates"
    assert article["source"] == "Fixture Times"
    assert article["published_at"] is not None
    assert article["content_hash"]


def test_default_news_query_uses_aliases():
    """Retrieval query favors recall (name + curated aliases); the agent's
    relevance screen enforces precision downstream."""
    from app.data.universe.universe_config import get_universe_entry

    q = default_news_query(get_universe_entry("RELIANCE"))
    assert '"Reliance Industries"' in q
    assert "RIL" in q
    assert '"Reliance Jio"' in q

    q = default_news_query(get_universe_entry("LT"))
    assert "Larsen & Toubro" in q
    assert "L&T" in q
    # Two-letter bare symbol excluded from the query too.
    assert " OR LT" not in q and not q.endswith(" LT")

    q = default_news_query(get_universe_entry("TCS"))
    assert '"Tata Consultancy Services"' in q and "TCS" in q


def test_refresh_uses_alias_query(stack):
    """The effective provider query carries aliases (observable in result)."""
    news_repo, provenance_repo = stack

    seen = {}

    class RecordingProvider(FixtureNewsProvider):
        def fetch_articles(self, query, from_date=None, to_date=None, page_size=50):
            seen["query"] = query
            return super().fetch_articles(query, from_date, to_date, page_size)

    service = NewsService(RecordingProvider(), news_repo, provenance_repo)
    result = service.refresh_entity_news("SBIN")
    assert result["query"] == seen["query"]
    assert '"State Bank of India"' in seen["query"]
    assert "SBI" in seen["query"]