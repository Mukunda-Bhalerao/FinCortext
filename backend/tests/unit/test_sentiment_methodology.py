"""Unit tests: sentiment probability processing and deterministic aggregation."""

from datetime import datetime, timedelta, timezone

from app.agents.sentiment.methodology import (
    CONFIDENCE_WEIGHTS,
    FULL_COVERAGE_ARTICLES,
    HALF_LIFE_DAYS,
    aggregate,
    polarity_score,
    recency_weight,
)


def _scored(label="positive", pos=0.8, neg=0.1, neu=0.1, conf=0.9, age_days=0.0, aid=None):
    return {
        "article_id": aid or f"a-{label}-{age_days}",
        "published_at": datetime(2024, 7, 15, tzinfo=timezone.utc) - timedelta(days=age_days),
        "label": label,
        "positive": pos,
        "neutral": neu,
        "negative": neg,
        "model_confidence": conf,
    }


# -- polarity ------------------------------------------------------------------

def test_polarity_score():
    assert polarity_score(0.9, 0.05) == 0.85
    assert polarity_score(0.05, 0.9) == -0.85
    assert polarity_score(0.5, 0.5) == 0.0


# -- recency weighting ------------------------------------------------------------

def test_recency_weight_half_life():
    ref = datetime(2024, 7, 15, tzinfo=timezone.utc)
    assert recency_weight(ref, ref) == 1.0
    # One half-life old → weight 0.5
    one_hl = ref - timedelta(days=HALF_LIFE_DAYS)
    assert abs(recency_weight(one_hl, ref) - 0.5) < 1e-9
    # Two half-lives → 0.25
    two_hl = ref - timedelta(days=2 * HALF_LIFE_DAYS)
    assert abs(recency_weight(two_hl, ref) - 0.25) < 1e-9
    # Missing timestamp → full weight
    assert recency_weight(None, ref) == 1.0
    # Future timestamps clamped to full weight
    future = ref + timedelta(days=3)
    assert recency_weight(future, ref) == 1.0


# -- aggregation -----------------------------------------------------------------

def test_aggregate_empty():
    assert aggregate([]) == {}


def test_aggregate_single_positive_article():
    result = aggregate([_scored()])
    # polarity 0.7 → score (0.7+1)/2*100 = 85
    assert result["score"] == 85.0
    assert result["article_count"] == 1
    assert result["distribution"]["positive"] == 1.0
    assert 0.0 <= result["confidence"] <= 1.0


def test_aggregate_score_bounds_and_neutral():
    result = aggregate([_scored(label="neutral", pos=0.34, neg=0.33, neu=0.33)])
    # polarity ≈ 0.01 → score ≈ 50.5
    assert 45.0 <= result["score"] <= 55.0


def test_aggregate_recency_dominance():
    """A fresh positive article outweighs an old negative one."""
    fresh_positive = _scored(label="positive", pos=0.9, neg=0.05, age_days=0.0, aid="fresh")
    old_negative = _scored(label="negative", pos=0.05, neg=0.9, age_days=28.0, aid="old")
    result = aggregate([fresh_positive, old_negative])
    # Fresh article has weight 1.0; 28 days = 4 half-lives → 1/16 ≈ 0.0625
    assert result["distribution"]["positive"] > result["distribution"]["negative"]
    assert result["score"] > 50.0


def test_aggregate_deterministic():
    articles = [
        _scored("positive", age_days=0.0, aid="a1"),
        _scored("negative", age_days=2.0, aid="a2"),
        _scored("neutral", age_days=5.0, aid="a3"),
    ]
    r1 = aggregate(articles)
    r2 = aggregate(list(reversed(articles)))
    # Order-independent (weights depend only on timestamps) and repeatable
    assert r1["score"] == r2["score"]
    assert r1["confidence"] == r2["confidence"]
    assert r1["distribution"] == r2["distribution"]
    again = aggregate(articles)
    assert r1 == again


def test_aggregate_distribution_sums_to_one():
    articles = [
        _scored("positive", age_days=0.0),
        _scored("negative", age_days=3.0),
        _scored("neutral", age_days=9.0),
        _scored("positive", age_days=1.0, aid="x"),
    ]
    result = aggregate(articles)
    total = sum(result["distribution"].values())
    assert abs(total - 1.0) < 1e-6


# -- confidence -------------------------------------------------------------------

def test_confidence_increases_with_coverage():
    few = aggregate([_scored(aid=f"p{i}") for i in range(2)])
    more = aggregate([_scored(aid=f"q{i}") for i in range(FULL_COVERAGE_ARTICLES)])
    assert more["confidence_components"]["coverage"] == 1.0
    assert few["confidence_components"]["coverage"] < 1.0
    assert more["confidence"] > few["confidence"]


def test_confidence_consistency_component():
    consistent = aggregate([_scored(aid=f"c{i}") for i in range(5)])  # all positive
    mixed = aggregate(
        [
            _scored("positive", pos=0.9, neg=0.05, aid="m1"),
            _scored("negative", pos=0.05, neg=0.9, aid="m2"),
            _scored("positive", pos=0.9, neg=0.05, aid="m3"),
            _scored("negative", pos=0.05, neg=0.9, aid="m4"),
        ]
    )
    assert consistent["confidence_components"]["consistency"] == 1.0
    assert mixed["confidence_components"]["consistency"] < 1.0
    assert consistent["confidence"] > mixed["confidence"]


def test_confidence_uses_model_confidence():
    high = aggregate([_scored(conf=0.99, aid="h1"), _scored(conf=0.99, aid="h2")])
    low = aggregate([_scored(conf=0.55, aid="l1"), _scored(conf=0.55, aid="l2")])
    assert high["confidence_components"]["model_confidence"] > low["confidence_components"]["model_confidence"]
    assert high["confidence"] > low["confidence"]


def test_confidence_weights_sum_to_one():
    assert abs(sum(CONFIDENCE_WEIGHTS.values()) - 1.0) < 1e-9