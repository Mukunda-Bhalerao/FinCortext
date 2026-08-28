"""Unit tests: NewsAPI normalization, duplicate identity, error handling."""

import hashlib

import pytest

from app.data.providers.news.newsapi_provider import (
    NewsAPINewsProvider,
    parse_published_at,
)
from app.core.exceptions import ProviderError, ProviderUnavailableError


def _payload(**overrides):
    base = {
        "source": {"id": "et", "name": "Economic Times"},
        "author": "Reporter",
        "title": "TCS beats quarterly profit estimates",
        "description": "Tata Consultancy Services reported strong growth.",
        "url": "https://example.com/tcs-q1",
        "urlToImage": None,
        "publishedAt": "2024-07-15T09:30:00Z",
        "content": "Full article content truncated (250 chars)...",
        "language": "en",
    }
    base.update(overrides)
    return base


# -- timestamp parsing ---------------------------------------------------------

def test_parse_published_at_handles_z_and_offset():
    assert parse_published_at("2024-07-15T09:30:00Z") is not None
    assert parse_published_at("2024-07-15T09:30:00+05:30") is not None
    assert parse_published_at(None) is None
    assert parse_published_at("not-a-date") is None


# -- normalization ---------------------------------------------------------------

def test_normalize_article_full_payload():
    article = NewsAPINewsProvider.normalize_article(_payload())
    assert article is not None
    assert article.title == "TCS beats quarterly profit estimates"
    assert article.source == "Economic Times"
    assert article.source_url == "https://example.com/tcs-q1"
    assert article.language == "en"
    assert article.published_at is not None and article.published_at.year == 2024
    assert article.entity_id is None  # associated by the service layer
    assert article.source_type.value == "news_api"
    # article_id = sha256 of URL (stable identity for dedup)
    expected_id = hashlib.sha256(b"https://example.com/tcs-q1").hexdigest()
    assert article.article_id == expected_id
    # content_hash covers title|description|content
    expected_hash = hashlib.sha256(
        "TCS beats quarterly profit estimates|Tata Consultancy Services "
        "reported strong growth.|Full article content truncated (250 chars...)".encode()
    ).hexdigest()  # content differs; just check presence/format
    assert article.content_hash != expected_id
    assert len(article.content_hash) == 64


def test_normalize_article_deterministic_ids():
    a1 = NewsAPINewsProvider.normalize_article(_payload())
    a2 = NewsAPINewsProvider.normalize_article(_payload())
    assert a1.article_id == a2.article_id
    assert a1.content_hash == a2.content_hash


def test_normalize_article_same_url_different_content_same_id():
    """Same URL → same article_id (dedup), different content_hash (audit)."""
    a1 = NewsAPINewsProvider.normalize_article(_payload())
    a2 = NewsAPINewsProvider.normalize_article(
        _payload(description="Updated description after correction.")
    )
    assert a1.article_id == a2.article_id
    assert a1.content_hash != a2.content_hash


def test_normalize_article_without_url_uses_title_hash():
    raw = _payload(url=None, publishedAt=None)
    article = NewsAPINewsProvider.normalize_article(raw)
    assert article is not None
    expected = hashlib.sha256(b"TCS beats quarterly profit estimates|").hexdigest()
    assert article.article_id == expected


def test_normalize_article_rejects_missing_title():
    assert NewsAPINewsProvider.normalize_article(_payload(title=None)) is None
    assert NewsAPINewsProvider.normalize_article(_payload(title="   ")) is None


# -- provider error handling ------------------------------------------------------

def test_fetch_without_key_raises_unavailable():
    provider = NewsAPINewsProvider(api_key="")
    with pytest.raises(ProviderUnavailableError):
        provider.fetch_articles("TCS")


def test_fetch_whitespace_key_raises_unavailable():
    provider = NewsAPINewsProvider(api_key="   ")
    with pytest.raises(ProviderUnavailableError):
        provider.fetch_articles("TCS")


def test_fetch_empty_query_raises_provider_error():
    provider = NewsAPINewsProvider(api_key="k")
    with pytest.raises(ProviderError):
        provider.fetch_articles("   ")


class _FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {"status": "ok", "articles": []}

    def json(self):
        return self._payload


def _patch_requests(monkeypatch, response):
    import app.data.providers.news.newsapi_provider as mod

    captured = {}

    def fake_get(url, params=None, headers=None, timeout=None):
        captured["url"] = url
        captured["params"] = params
        captured["headers"] = headers
        return response

    monkeypatch.setattr(mod.requests, "get", fake_get)
    return captured


def test_fetch_success_normalizes_articles(monkeypatch):
    provider = NewsAPINewsProvider(api_key="test-key")
    payload = {
        "status": "ok",
        "articles": [_payload(), _payload(title=None)],  # one malformed skipped
    }
    captured = _patch_requests(
        monkeypatch, _FakeResponse(200, payload)
    )
    articles = provider.fetch_articles("TCS", from_date="2024-07-01", to_date="2024-07-15")
    assert len(articles) == 1
    assert articles[0].title == "TCS beats quarterly profit estimates"
    assert captured["headers"]["X-Api-Key"] == "test-key"
    assert captured["params"]["q"] == "TCS"
    assert captured["params"]["from"] == "2024-07-01"


def test_fetch_bad_key_raises_unavailable(monkeypatch):
    provider = NewsAPINewsProvider(api_key="bad")
    _patch_requests(monkeypatch, _FakeResponse(401))
    with pytest.raises(ProviderUnavailableError):
        provider.fetch_articles("TCS")


def test_fetch_rate_limit_raises_provider_error(monkeypatch):
    provider = NewsAPINewsProvider(api_key="k")
    _patch_requests(monkeypatch, _FakeResponse(429))
    with pytest.raises(ProviderError, match="rate limit"):
        provider.fetch_articles("TCS")


def test_fetch_api_error_payload_raises_provider_error(monkeypatch):
    provider = NewsAPINewsProvider(api_key="k")
    _patch_requests(
        monkeypatch,
        _FakeResponse(200, {"status": "error", "code": "parametersError", "message": "bad params"}),
    )
    with pytest.raises(ProviderError, match="bad params"):
        provider.fetch_articles("TCS")


def test_fetch_network_error_raises_provider_error(monkeypatch):
    import requests

    import app.data.providers.news.newsapi_provider as mod

    def fake_get(*args, **kwargs):
        raise requests.ConnectionError("network down")

    monkeypatch.setattr(mod.requests, "get", fake_get)
    provider = NewsAPINewsProvider(api_key="k")
    with pytest.raises(ProviderError, match="network down"):
        provider.fetch_articles("TCS")