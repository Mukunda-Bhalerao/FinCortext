"""Unit tests: Google News RSS provider (mocked HTTP, no network).

Covers: item parsing (" - Source" suffix, HTML snippets, pubDate),
query-variant order with >=5 stop rule, Yahoo secondary fallback,
6h cache hit/miss, retry-then-failure -> ProviderError (existing graceful
UNAVAILABLE path), and NewsService primary+secondary merge/dedup.
"""

import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import pytest

from app.data.providers.news.googlenews_rss import (
    GoogleNewsRssProvider,
    parse_published_at,
    query_variants,
    rss_query_variants,
    split_title_source,
)
from app.data.storage.duckdb_storage import DuckDBStorage
from app.domain.contracts.providers import NewsProvider
from app.domain.models.news import NewsArticle
from app.repositories.news_repository import NewsRepository
from app.repositories.provenance_repository import ProvenanceRepository
from app.services.news_service import NewsService


def _rss_xml(items):
    body = "".join(
        "<item>"
        f"<title>{title}</title>"
        f"<link>{link}</link>"
        f"<pubDate>{pub}</pubDate>"
        f"<description>{desc}</description>"
        f"<source url=\"{source_url}\">{source}</source>"
        "</item>"
        for title, link, pub, desc, source_url, source in items
    )
    return f'<?xml version="1.0"?><rss version="2.0"><channel><title>test</title>{body}</channel></rss>'


GOOGLE_ITEMS = [
    (
        "Adani Power shares jump 5% on strong results - The Economic Times",
        "https://news.google.com/rss/articles/CBMiX1",
        "Mon, 22 Sep 2026 07:00:00 GMT",
        "<a href=\"x\">Adani Power</a> shares <b>jumped</b> 5% after quarterly results beat estimates.",
        "https://economictimes.indiatimes.com",
        "The Economic Times",
    ),
    (
        "NTPC commissions new solar unit",
        "https://news.google.com/rss/articles/CBMiY2",
        "Tue, 23 Sep 2026 09:30:00 GMT",
        "State-run NTPC added capacity.",
        "https://example.com",
        "Example Wire",
    ),
]


class FakeResponse:
    def __init__(self, text, status_code=200):
        self.content = text.encode("utf-8")
        self.status_code = status_code
        self.text = text


class FakeHttp:
    """Monkeypatched requests.get: scripted responses per URL fragment."""

    def __init__(self, mapping):
        # mapping: substring -> list of FakeResponse/Exception to pop
        self.mapping = {k: list(v) for k, v in mapping.items()}
        self.calls: list[str] = []

    def __call__(self, url, params=None, headers=None, timeout=None):
        target = url + "?" + "&".join(f"{k}={v}" for k, v in (params or {}).items())
        self.calls.append(target)
        for fragment, queue in self.mapping.items():
            if fragment in target:
                if not queue:
                    raise AssertionError(f"out of scripted responses for {fragment}")
                outcome = queue.pop(0)
                if isinstance(outcome, Exception):
                    raise outcome
                return outcome
        raise AssertionError(f"unexpected request: {target}")


@pytest.fixture()
def provider():
    return GoogleNewsRssProvider()


# -- parsing helpers ------------------------------------------------------------


def test_split_title_source_suffix():
    title, source = split_title_source("Adani Power shares jump - The Economic Times")
    assert title == "Adani Power shares jump"
    assert source == "The Economic Times"


def test_split_title_source_keeps_hyphen_headlines():
    title, source = split_title_source("Power-sector rally lifts Adani Power outlook")
    assert title == "Power-sector rally lifts Adani Power outlook"
    assert source is None


def test_split_title_source_empty_tail_kept():
    title, source = split_title_source("Headline - ")
    assert title == "Headline -"
    assert source is None


def test_parse_published_at_rfc2822():
    dt = parse_published_at("Mon, 22 Sep 2026 07:00:00 GMT")
    assert dt is not None and dt.year == 2026 and dt.tzinfo is not None
    assert parse_published_at("not a date") is None
    assert parse_published_at(None) is None


def test_query_variants_order_and_dedup():
    variants = query_variants("Adani Power", "ADANI POWER LTD", "ADANIPOWER")
    assert len(variants) == 3
    assert variants[0].startswith('"Adani Power"')
    assert "when:30d" in variants[0]
    assert variants[2].startswith("ADANIPOWER NSE")
    # Identical short/full collapse to fewer variants.
    assert len(query_variants("Infosys", "Infosys", "INFY")) == 2


def test_rss_query_variants_pipe_shape():
    from app.data.universe.universe_config import get_universe_entry

    variants = rss_query_variants(get_universe_entry("TCS"))
    assert variants
    assert variants[0].count("|") == 2
    assert "TCS" in variants[0]


# -- fetching ---------------------------------------------------------------------


def _google_http(*xmls, yahoo_xml=None):
    """Script one response per Google variant (3 max) plus Yahoo fallback."""
    mapping = {"news.google.com": [FakeResponse(x) for x in xmls]}
    yahoo = FakeResponse(yahoo_xml if yahoo_xml is not None else _rss_xml([]))
    # One Yahoo response per Google fetch (tests may fetch repeatedly).
    mapping["feeds.finance.yahoo.com"] = [yahoo] * max(1, len(xmls))
    return FakeHttp(mapping)


def _patch_http(monkeypatch, http):
    monkeypatch.setattr("app.data.providers.news.googlenews_rss.requests.get", http)
    monkeypatch.setattr("app.data.providers.news.googlenews_rss.MIN_REQUEST_INTERVAL_SECONDS", 0)
    return http


def test_google_variant_parses_items(provider, monkeypatch):
    xml = _rss_xml(GOOGLE_ITEMS)
    http = _patch_http(monkeypatch, _google_http(xml, xml, xml))
    articles = provider.fetch_articles("Adani Power|ADANI POWER LTD|ADANIPOWER")
    assert len(articles) == 2
    first = articles[0]
    assert first.title == "Adani Power shares jump 5% on strong results"
    assert first.source == "The Economic Times"
    assert first.description == "Adani Power shares jumped 5% after quarterly results beat estimates."
    assert first.published_at == datetime(2026, 9, 22, 7, 0, tzinfo=timezone.utc)
    assert first.source_url == "https://news.google.com/rss/articles/CBMiX1"
    assert first.source_name == "google_news_rss"
    import hashlib

    assert first.article_id == hashlib.sha256(first.source_url.encode()).hexdigest()


def test_variant_order_stops_at_first_with_enough_items(provider, monkeypatch):
    items = [
        (
            f"Adani Power story {i}",
            f"https://news.google.com/rss/articles/UNIQ{i}",
            "Mon, 22 Sep 2026 07:00:00 GMT",
            f"Adani Power shares move on story {i}.",
            "https://example.com",
            "Example Wire",
        )
        for i in range(6)
    ]
    http = _patch_http(monkeypatch, _google_http(_rss_xml(items)))
    articles = provider.fetch_articles("Adani Power|ADANI POWER LTD|ADANIPOWER", page_size=50)
    assert len(articles) == 6  # 6 unique items -> stop after variant 1
    assert len([c for c in http.calls if "news.google.com" in c]) == 1
    assert not [c for c in http.calls if "yahoo" in c]  # no fallback needed


def test_yahoo_fallback_when_google_thin(provider, monkeypatch):
    thin = _rss_xml(GOOGLE_ITEMS[:1])  # 1 item < 5 -> Yahoo tried
    yahoo = _rss_xml([
        ("Adani Power outlook raised", "https://yahoo.com/a1", "Wed, 24 Sep 2026 10:00:00 GMT",
         "Brokerage raises target.", "https://yahoo.com", "Yahoo Finance"),
    ])
    http = _patch_http(monkeypatch, _google_http(thin, thin, thin, yahoo_xml=yahoo))
    articles = provider.fetch_articles("Adani Power|ADANI POWER LTD|ADANIPOWER")
    urls = {a.source_url for a in articles}
    assert "https://yahoo.com/a1" in urls
    assert any(a.source == "Yahoo Finance" for a in articles)


def test_yahoo_dedups_against_google(provider, monkeypatch):
    dup = _rss_xml([GOOGLE_ITEMS[0]])
    http = _patch_http(monkeypatch, _google_http(dup, dup, dup, yahoo_xml=dup))
    articles = provider.fetch_articles("Adani Power|X|ADANIPOWER")
    assert len(articles) == 1


def test_six_hour_cache_hit(provider, monkeypatch):
    http = _patch_http(monkeypatch, _google_http(_rss_xml(GOOGLE_ITEMS * 3)))
    first = provider.fetch_articles("Adani Power|X|ADANIPOWER")
    second = provider.fetch_articles("Adani Power|X|ADANIPOWER")
    assert [a.article_id for a in first] == [a.article_id for a in second]
    google_calls = [c for c in http.calls if "news.google.com" in c]
    assert len(google_calls) == 1  # second call served from cache


def test_cache_expiry_refetches(provider, monkeypatch):
    import app.data.providers.news.googlenews_rss as rss_mod

    xml = _rss_xml(GOOGLE_ITEMS * 3)
    http = _patch_http(monkeypatch, _google_http(xml, xml))
    monkeypatch.setattr(rss_mod, "CACHE_TTL_SECONDS", 0)
    provider.fetch_articles("Adani Power|X|ADANIPOWER")
    # Force the cached entry stale even with TTL edge semantics.
    for key in list(provider._cache):
        fetched_at, arts = provider._cache[key]
        provider._cache[key] = (fetched_at - 10**6, arts)
    provider.fetch_articles("Adani Power|X|ADANIPOWER")
    google_calls = [c for c in http.calls if "news.google.com" in c]
    assert len(google_calls) == 2


def test_retry_then_failure_raises_provider_error(provider, monkeypatch):
    import requests as _requests

    from app.core.exceptions import ProviderError

    http = FakeHttp({
        "news.google.com": [
            _requests.ConnectionError("down"),
            _requests.Timeout("slow"),
            FakeResponse("nope", status_code=500),
        ] * 4,
        "feeds.finance.yahoo.com": [FakeResponse("nope", status_code=500)] * 4,
    })
    _patch_http(monkeypatch, http)
    with pytest.raises(ProviderError):
        provider.fetch_articles("Adani Power|X|ADANIPOWER")


def test_malformed_xml_raises_provider_error(provider, monkeypatch):
    from app.core.exceptions import ProviderError

    http = FakeHttp({
        "news.google.com": [FakeResponse("<<< not xml")] * 3,
        "feeds.finance.yahoo.com": [FakeResponse("<<< not xml")] * 2,
    })
    _patch_http(monkeypatch, http)
    with pytest.raises(ProviderError):
        provider.fetch_articles("Adani Power|X|ADANIPOWER")


def test_items_without_titles_skipped(provider, monkeypatch):
    xml = (
        '<?xml version="1.0"?><rss version="2.0"><channel>'
        "<item><link>https://x.test/1</link></item>"
        + "".join(
            f"<item><title>{t}</title><link>https://x.test/{i}</link></item>"
            for i, t in enumerate(["Real headline here", "Second headline"])
        )
        + "</channel></rss>"
    )
    http = FakeHttp({
        "news.google.com": [FakeResponse(xml)] * 3,
        "feeds.finance.yahoo.com": [FakeResponse(_rss_xml([]))],
    })
    _patch_http(monkeypatch, http)
    articles = provider.fetch_articles("X|Y|Z")
    assert {a.title for a in articles} == {"Real headline here", "Second headline"}


# -- service merge ------------------------------------------------------------------


@pytest.fixture()
def news_stack(tmp_path):
    storage = DuckDBStorage(tmp_path / "rss_merge.duckdb")
    storage.connect()
    yield NewsRepository(storage), ProvenanceRepository(storage)
    storage.close()


def _stored_article(url, title):
    import hashlib

    return NewsArticle(
        article_id=hashlib.sha256(url.encode()).hexdigest(),
        title=title,
        description="shares jump on results",
        content=None,
        source="T",
        source_url=url,
        published_at=datetime(2026, 9, 22, 7, 0, tzinfo=timezone.utc),
        language="en",
        content_hash=hashlib.sha256(title.encode()).hexdigest(),
    )


class _StubProvider(NewsProvider):
    name = "stub"

    def __init__(self, articles=None, error=None, configured=True):
        self._articles = articles or []
        self._error = error
        self.is_configured = configured
        self.calls: list[str] = []

    def fetch_articles(self, query, from_date=None, to_date=None, page_size=50):
        self.calls.append(query)
        if self._error is not None:
            raise self._error
        return list(self._articles)


def test_service_merges_primary_and_secondary_with_dedup(news_stack):
    from app.core.exceptions import ProviderError

    news_repo, provenance_repo = news_stack
    shared = _stored_article("https://x.test/shared", "Shared story shares jump")
    primary = _StubProvider(articles=[shared, _stored_article("https://x.test/p1", "Primary shares up")])
    secondary = _StubProvider(articles=[shared, _stored_article("https://x.test/s1", "Secondary shares up")])
    secondary.name = "stub_secondary"
    service = NewsService(primary, news_repo, provenance_repo, secondary_provider=secondary)
    result = service.refresh_entity_news("TCS")
    assert result["status"] == "LIVE"
    assert result["fetched"] == 4  # associated before dedup
    assert result["stored"] == 3  # shared counted once after dedup
    assert result["duplicates"] == 1
    assert result["secondary_provider"] == "stub_secondary"
    assert result["secondary_fetched"] == 2
    assert news_repo.count("TCS") == 3


def test_service_secondary_rescues_primary_failure(news_stack):
    from app.core.exceptions import ProviderError

    news_repo, provenance_repo = news_stack
    primary = _StubProvider(error=ProviderError("primary down", details={"provider": "stub"}))
    secondary = _StubProvider(articles=[_stored_article("https://x.test/s1", "Only secondary shares")])
    secondary.name = "stub_secondary"
    service = NewsService(primary, news_repo, provenance_repo, secondary_provider=secondary)
    result = service.refresh_entity_news("TCS")
    assert result["status"] == "LIVE"
    assert result["stored"] == 1


def test_service_both_fail_reports_error(news_stack):
    from app.core.exceptions import ProviderError

    news_repo, provenance_repo = news_stack
    primary = _StubProvider(error=ProviderError("p1 down", details={"provider": "a"}))
    secondary = _StubProvider(error=ProviderError("p2 down", details={"provider": "b"}))
    service = NewsService(primary, news_repo, provenance_repo, secondary_provider=secondary)
    result = service.refresh_entity_news("TCS")
    assert result["status"] == "ERROR"


def test_rss_provider_status_shape():
    service = NewsService(
        GoogleNewsRssProvider(), NewsRepository.__new__(NewsRepository),
        ProvenanceRepository.__new__(ProvenanceRepository),
    )
    status = service.get_status()
    assert status["provider"] == "google_news_rss"
    assert status["configured"] is True
    assert status["status"] == "LIVE"
