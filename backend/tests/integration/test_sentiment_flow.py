"""Integration: fixture news provider → storage → SentimentAgent → API output."""

import hashlib
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.data.storage.duckdb_storage import DuckDBStorage
from app.domain.contracts.providers import NewsProvider
from app.domain.models.news import NewsArticle
from app.main import create_app
from app.repositories.agent_output_repository import AgentOutputRepository
from app.repositories.financial_repository import FinancialRepository
from app.repositories.market_repository import MarketRepository
from app.repositories.news_repository import NewsRepository
from app.repositories.provenance_repository import ProvenanceRepository
from app.services.agent_service import AgentService
from app.services.news_service import NewsService


class FakeSentimentModel:
    """Deterministic keyword-driven stand-in for FinBERT."""

    model_id = "fake-finbert"

    def analyze(self, texts):
        results = []
        for text in texts:
            lowered = text.lower()
            if any(w in lowered for w in ("beats", "surges", "record", "strong")):
                results.append({"label": "positive", "positive": 0.9, "neutral": 0.07, "negative": 0.03, "confidence": 0.9})
            elif any(w in lowered for w in ("falls", "probe", "loss")):
                results.append({"label": "negative", "positive": 0.05, "neutral": 0.1, "negative": 0.85, "confidence": 0.88})
            else:
                results.append({"label": "neutral", "positive": 0.3, "neutral": 0.5, "negative": 0.2, "confidence": 0.7})
        return results


class FixtureNewsProvider(NewsProvider):
    name = "fixture_news"

    def __init__(self, articles):
        self.articles = articles
        self.is_configured = True

    def fetch_articles(self, query, from_date=None, to_date=None, page_size=50):
        return list(self.articles)


def _article(url, title, published):
    return NewsArticle(
        article_id=hashlib.sha256(url.encode()).hexdigest(),
        title=title,
        description=None,
        content=None,
        source="Fixture Times",
        source_url=url,
        published_at=published,
        language="en",
        content_hash=hashlib.sha256(title.encode()).hexdigest(),
    )


@pytest.fixture()
def stack(tmp_path):
    storage = DuckDBStorage(tmp_path / "flow.duckdb")
    storage.connect()
    market_repo = MarketRepository(storage)
    financial_repo = FinancialRepository(storage)
    news_repo = NewsRepository(storage)
    output_repo = AgentOutputRepository(storage)
    provenance_repo = ProvenanceRepository(storage)

    base = datetime(2024, 7, 15, tzinfo=timezone.utc)
    provider = FixtureNewsProvider(
        [
            _article("https://x.com/1", "TCS beats quarterly estimates", base - timedelta(days=1)),
            _article("https://x.com/2", "TCS surges to record profit", base - timedelta(days=2)),
            _article("https://x.com/3", "TCS wins large deal, strong outlook", base - timedelta(days=3)),
            _article("https://x.com/4", "Crude oil slips on demand worries", base - timedelta(days=4)),
        ]
    )
    news_service = NewsService(provider, news_repo, provenance_repo)
    agent_service = AgentService(
        financial_repo,
        market_repo,
        output_repo,
        news_repo=news_repo,
        sentiment_model=FakeSentimentModel(),
    )
    yield news_service, agent_service, news_repo
    storage.close()


def test_news_to_sentiment_end_to_end(stack):
    news_service, agent_service, news_repo = stack

    # 1. Fixture provider → storage (dedup + provenance)
    refresh = news_service.refresh_entity_news("TCS")
    assert refresh["status"] == "LIVE"
    assert refresh["stored"] == 4
    assert news_repo.count("TCS") == 4

    # 2. Sentiment agent consumes stored articles
    output = agent_service.run_agent("sentiment_analyst", "TCS")
    assert output.agent_id.value == "sentiment_analyst"
    assert output.status == "OK"
    assert output.score is not None and 0 <= output.score <= 100
    # 3 relevant (TCS) of 4 stored; oil article filtered out
    assert output.provenance["articles_stored"] == 4
    assert output.provenance["articles_relevant"] == 3
    assert output.score > 50  # positive fixture news
    assert len(output.evidence) == 3
    assert any("oil" not in (e.note or "").lower() for e in output.evidence)

    # 3. Deterministic re-run without double-persisting
    out2 = agent_service.run_agent("sentiment_analyst", "TCS", persist=False)
    assert out2.score == output.score
    assert out2.confidence == output.confidence

    # 4. Per-article sentiment results persisted
    assert len(news_repo.get_sentiment_results("TCS")) == 3


def test_sentiment_agent_api_endpoint(tmp_path, monkeypatch, stack):
    news_service, agent_service, _ = stack
    news_service.refresh_entity_news("TCS")

    import app.api.routes.agents as agents_routes

    class TestContainer:
        pass

    TestContainer.agent_service = agent_service
    monkeypatch.setattr(agents_routes, "get_container", lambda: TestContainer())
    client = TestClient(create_app())

    r = client.post("/api/agents/sentiment/TCS/run")
    assert r.status_code == 200
    body = r.json()
    assert body["agent_id"] == "sentiment_analyst"
    assert body["score"] is not None
    assert body["status"] in {"OK", "DEGRADED"}
    assert len(body["factors"]) == 4

    r = client.get("/api/agents/outputs?agent_id=sentiment_analyst&symbol=TCS")
    assert r.status_code == 200
    assert r.json()["count"] == 1


def test_news_api_endpoints_with_missing_key(tmp_path, monkeypatch, stack):
    """Missing NEWS_API_KEY → graceful UNAVAILABLE, stored news still readable."""
    news_service, agent_service, _ = stack

    import app.api.routes.news as news_routes

    class TestContainer:
        pass

    TestContainer.news_service = news_service
    monkeypatch.setattr(news_routes, "get_container", lambda: TestContainer())
    client = TestClient(create_app())

    # Status: provider not configured
    class Unconfigured(FixtureNewsProvider):
        def __init__(self):
            super().__init__([])
            self.is_configured = False

    news_service.provider = Unconfigured()

    r = client.get("/api/news/status")
    assert r.status_code == 200
    body = r.json()
    assert body["configured"] is False
    assert body["status"] == "UNAVAILABLE"

    # Refresh without key → explicit UNAVAILABLE (no crash, no fabrication)
    r = client.post("/api/news/refresh/TCS")
    assert r.status_code == 200
    assert r.json()["status"] == "UNAVAILABLE"
    assert "NEWS_API_KEY" in r.json()["message"]

    # Stored news endpoint still functional
    r = client.get("/api/news/TCS")
    assert r.status_code == 200
    assert r.json()["symbol"] == "TCS"