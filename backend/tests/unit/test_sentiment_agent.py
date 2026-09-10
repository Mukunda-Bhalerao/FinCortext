"""Unit tests: SentimentAgent behavior with a fake model (no network, no FinBERT)."""

import hashlib
from datetime import datetime, timedelta, timezone

import pytest

from app.agents.sentiment.sentiment_agent import SentimentAgent, clean_text
from app.agents.sentiment.relevance import assess_relevance
from app.data.universe.universe_config import get_universe_entry
from app.core.exceptions import ModelUnavailableError
from app.data.storage.duckdb_storage import DuckDBStorage
from app.domain.models.news import NewsArticle
from app.repositories.agent_output_repository import AgentOutputRepository
from app.repositories.news_repository import NewsRepository


class FakeSentimentModel:
    """Deterministic fake: scores by keyword, mimics the FinBERT interface."""

    model_id = "fake-finbert"

    def __init__(self, unavailable: bool = False):
        self.unavailable = unavailable

    def analyze(self, texts):
        if self.unavailable:
            raise ModelUnavailableError("fake model unavailable")
        results = []
        for text in texts:
            lowered = text.lower()
            if any(w in lowered for w in ("beats", "surges", "record profit", "strong")):
                results.append(
                    {"label": "positive", "positive": 0.9, "neutral": 0.07, "negative": 0.03, "confidence": 0.9}
                )
            elif any(w in lowered for w in ("falls", "probe", "scandal", "loss")):
                results.append(
                    {"label": "negative", "positive": 0.05, "neutral": 0.1, "negative": 0.85, "confidence": 0.88}
                )
            else:
                results.append(
                    {"label": "neutral", "positive": 0.3, "neutral": 0.5, "negative": 0.2, "confidence": 0.6}
                )
        return results


def _article(url, title, published=None, description=None, content=None):
    return NewsArticle(
        article_id=hashlib.sha256(url.encode()).hexdigest(),
        title=title,
        description=description,
        content=content,
        source="Fixture Times",
        source_url=url,
        published_at=published,
        language="en",
        entity_id="TCS",
        content_hash=hashlib.sha256(title.encode()).hexdigest(),
    )


def _seed(news_repo, articles):
    news_repo.save_articles(articles)


@pytest.fixture()
def stack(tmp_path):
    storage = DuckDBStorage(tmp_path / "sentiment.duckdb")
    storage.connect()
    news_repo = NewsRepository(storage)
    output_repo = AgentOutputRepository(storage)
    yield news_repo, output_repo
    storage.close()


# -- text helpers -----------------------------------------------------------------

def test_clean_text_collapses_whitespace():
    assert clean_text("  TCS   beats ", None, " estimates  ") == "TCS beats estimates"
    assert clean_text(None, None) == ""


def _verdict(text, symbol="TCS"):
    entry = get_universe_entry(symbol)
    return assess_relevance(text, None, None, entry)


def test_relevance_needs_identity_and_financial_context():
    assert _verdict("Tata Consultancy Services wins large deal").relevant
    assert _verdict("TCS shares surge").relevant
    assert _verdict("TCS beats quarterly estimates").relevant
    # Symbol must match as a whole word — not inside other words
    assert not _verdict("switches and circuits").relevant
    assert not _verdict("Unrelated commodity news").relevant
    # Identity alone is not enough: no financial/business context
    v = _verdict("From TCS to Microsoft, techie details 6 things different")
    assert not v.relevant and v.reason == "no_financial_context"
    # Sponsored sport carries no investment signal even with a mention
    v = _verdict("How to Watch the TCS Sydney Marathon 2026")
    assert not v.relevant and v.reason == "excluded_topic"
    # Personal tragedy is not analyzable company news
    v = _verdict("TCS engineer on way home dies after reversing earthmover rams bike")
    assert not v.relevant and v.reason == "excluded_topic"


# -- agent behavior -----------------------------------------------------------------

def test_no_articles_unavailable(stack):
    news_repo, output_repo = stack
    agent = SentimentAgent(news_repo, output_repo, FakeSentimentModel())
    out = agent.analyze("TCS")
    assert out.score is None
    assert out.status == "UNAVAILABLE"
    assert out.signal.value == "unavailable"
    assert any("No stored news" in lim for lim in out.data_limitations)


def test_irrelevant_articles_unavailable(stack):
    news_repo, output_repo = stack
    _seed(
        news_repo,
        [_article("https://x.com/1", "Crude oil prices move sideways", datetime(2024, 7, 10, tzinfo=timezone.utc))],
    )
    agent = SentimentAgent(news_repo, output_repo, FakeSentimentModel())
    out = agent.analyze("TCS")
    assert out.status == "UNAVAILABLE"
    assert any("no mention" in lim for lim in out.data_limitations)


def test_model_unavailable_degrades_without_crash(stack):
    news_repo, output_repo = stack
    _seed(
        news_repo,
        [
            _article("https://x.com/1", "TCS beats estimates", datetime(2024, 7, 10, tzinfo=timezone.utc)),
            _article("https://x.com/2", "TCS surges on strong demand", datetime(2024, 7, 11, tzinfo=timezone.utc)),
            _article("https://x.com/3", "TCS records profit growth", datetime(2024, 7, 12, tzinfo=timezone.utc)),
        ],
    )
    agent = SentimentAgent(news_repo, output_repo, FakeSentimentModel(unavailable=True))
    out = agent.analyze("TCS")  # must NOT raise
    assert out.score is None
    assert out.status == "UNAVAILABLE"
    assert any("model unavailable" in lim.lower() for lim in out.data_limitations)
    assert "fake-finbert" in out.provenance.get("model_id", "")


def test_positive_articles_ok_status(stack):
    news_repo, output_repo = stack
    base = datetime(2024, 7, 15, tzinfo=timezone.utc)
    _seed(
        news_repo,
        [
            _article("https://x.com/1", "TCS beats quarterly estimates", base - timedelta(days=1)),
            _article("https://x.com/2", "TCS surges on record profit", base - timedelta(days=2)),
            _article("https://x.com/3", "TCS reports strong demand", base - timedelta(days=3)),
        ],
    )
    agent = SentimentAgent(news_repo, output_repo, FakeSentimentModel())
    out = agent.analyze("TCS")
    assert out.agent_id.value == "sentiment_analyst"
    assert out.status == "OK"
    assert out.score is not None and out.score > 50  # all positive
    assert out.signal.value == "strong_buy"  # score 85 ≥ 70
    assert 0 < out.confidence <= 1
    # factors present and explainable
    names = {f.name for f in out.factors}
    assert {"news_volume", "model_confidence", "sentiment_consistency", "recency"} == names
    # evidence references articles
    assert len(out.evidence) == 3
    assert all(e.data_type == "news_article" for e in out.evidence)
    # provenance
    assert out.provenance["methodology"] == "sentiment_analyst_v1"
    assert out.provenance["articles_relevant"] == 3
    # per-article sentiment results persisted
    saved = news_repo.get_sentiment_results("TCS")
    assert len(saved) == 3
    assert all(r.model_id == "fake-finbert" for r in saved)


def test_thin_evidence_degraded_status(stack):
    news_repo, output_repo = stack
    base = datetime(2024, 7, 15, tzinfo=timezone.utc)
    _seed(
        news_repo,
        [_article("https://x.com/1", "TCS beats estimates", base - timedelta(days=1))],
    )
    agent = SentimentAgent(news_repo, output_repo, FakeSentimentModel())
    out = agent.analyze("TCS")
    assert out.status == "DEGRADED"
    assert out.score is not None
    assert any("Thin evidence" in lim for lim in out.data_limitations)


def test_deterministic_rerun(stack):
    news_repo, output_repo = stack
    base = datetime(2024, 7, 15, tzinfo=timezone.utc)
    _seed(
        news_repo,
        [
            _article("https://x.com/1", "TCS beats estimates", base - timedelta(days=1)),
            _article("https://x.com/2", "TCS falls on profit booking", base - timedelta(days=2)),
            _article("https://x.com/3", "TCS outlook stable", base - timedelta(days=3)),
        ],
    )
    agent = SentimentAgent(news_repo, output_repo, FakeSentimentModel())
    out1 = agent.run("TCS", persist=False)
    out2 = agent.run("TCS", persist=False)
    assert out1.score == out2.score
    assert out1.confidence == out2.confidence
    assert out1.rationale == out2.rationale
    assert [f.contribution for f in out1.factors] == [f.contribution for f in out2.factors]


def test_screening_counts_and_excludes_noise(stack):
    """Mixed real-world store: only company-financial articles are scored;
    sponsorships, anecdotes and digests are rejected with auditable counts."""
    news_repo, output_repo = stack
    base = datetime(2024, 7, 15, tzinfo=timezone.utc)
    _seed(
        news_repo,
        [
            _article("https://x.com/1", "TCS employees get 50-70% variable in Q1", base),
            _article(
                "https://x.com/2",
                "Tejas Networks shares zoom 13% after TCS's Rs 1,537-crore LOI",
                base - timedelta(days=1),
            ),
            _article("https://x.com/3", "How to Watch the TCS Sydney Marathon 2026", base),
            _article(
                "https://x.com/4",
                "From TCS to Microsoft, techie details 6 things different",
                base,
            ),
            _article("https://x.com/5", "Sensex today: Nifty ends flat", base),
        ],
    )
    agent = SentimentAgent(news_repo, output_repo, FakeSentimentModel())
    out = agent.analyze("TCS")
    assert out.status in {"OK", "DEGRADED"}
    assert out.provenance["articles_stored"] == 5
    assert out.provenance["articles_relevant"] == 2
    assert out.provenance["articles_rejected"] == 3
    assert out.provenance["rejected_no_identity"] == 1  # Sensex digest
    assert out.provenance["rejected_no_financial_context"] == 1  # career anecdote
    assert out.provenance["rejected_excluded_topic"] == 1  # marathon
    # Only the 2 relevant articles were scored and persisted.
    assert len(news_repo.get_sentiment_results("TCS")) == 2
    titles = " ".join((e.note or "") for e in out.evidence)
    assert "Marathon" not in titles
    assert "Microsoft" not in titles
    # Limitations disclose the screening, never hide it.
    assert any("5 stored" in lim and "2 relevant" in lim for lim in out.data_limitations)


def test_identity_without_financial_context_unavailable(stack):
    """Mentions without business context score nothing — with examples."""
    news_repo, output_repo = stack
    base = datetime(2024, 7, 15, tzinfo=timezone.utc)
    _seed(
        news_repo,
        [
            _article("https://x.com/1", "How to Watch the TCS Sydney Marathon 2026", base),
            _article("https://x.com/2", "TCS engineer dies in road accident", base),
        ],
    )
    agent = SentimentAgent(news_repo, output_repo, FakeSentimentModel())
    out = agent.analyze("TCS")
    assert out.status == "UNAVAILABLE"
    assert out.score is None
    assert out.provenance["articles_relevant"] == 0
    assert out.provenance["articles_rejected"] == 2
    assert any("financial/business context" in lim for lim in out.data_limitations)