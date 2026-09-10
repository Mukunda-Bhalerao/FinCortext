"""Sentiment Analyst scoring methodology — fully documented, deterministic.

Answers: "What does recent relevant news sentiment say about the company?"

## Pipeline

    stored articles (NewsRepository)
        → relevance filter (company identity AND financial/business context,
          excluded sponsorship/tragedy topics; deterministic — see
          relevance.py for the documented identifier and keyword sets)
        → text preparation (title + description, whitespace-collapsed)
        → FinBERT inference (local model, eval mode, no sampling)
        → per-article polarity = P(positive) − P(negative)  ∈ [−1, +1]
        → recency-weighted aggregation (weights anchored to the DATA, not
          the wall clock — see below)
        → composite score 0–100 + confidence + label distribution

## Recency weighting (time-aware, deterministic)

Each relevant article gets weight

    w_i = 0.5 ** (age_days_i / HALF_LIFE_DAYS)

where `age_days_i` is measured against `reference_ts` = the **latest
published_at among the analyzed articles** (not the current time). This makes
re-runs on the same stored data produce byte-identical results — the
aggregation is anchored to the data, never to the wall clock. Articles with
no published_at get age 0 (full weight) and are flagged in limitations.

## Composite score

    weighted_mean_polarity = Σ (w_i × polarity_i) / Σ w_i      ∈ [−1, +1]
    score                  = (weighted_mean_polarity + 1) / 2 × 100   ∈ [0, 100]

Label distribution = normalized weight share per predicted label
(positive_weight + neutral_weight + negative_weight = 1).

## Confidence (documented components, all deterministic)

    confidence = 0.35 × coverage + 0.25 × model_confidence
               + 0.25 × consistency + 0.15 × recency_share

- coverage    = min(1, n_relevant / FULL_COVERAGE_ARTICLES)   (10 articles → 1.0)
- model_confidence = mean predicted-label probability of the model
- consistency = 1 − population std-dev of article polarities (agreement
  measure, clamped to [0, 1])
- recency     = share of total weight held by articles within one half-life
  of the reference timestamp

No randomness anywhere. Empty/insufficient input → score None, confidence 0.
"""

from __future__ import annotations

from datetime import datetime

HALF_LIFE_DAYS = 7.0          # exponential recency decay half-life
FULL_COVERAGE_ARTICLES = 10   # article count considered "full coverage"
MIN_ARTICLES_FOR_OK = 3       # below this → status DEGRADED (thin evidence)

CONFIDENCE_WEIGHTS = {
    "coverage": 0.35,
    "model_confidence": 0.25,
    "consistency": 0.25,
    "recency": 0.15,
}


def polarity_score(positive: float, negative: float) -> float:
    """Article polarity ∈ [−1, +1]: P(positive) − P(negative)."""
    return positive - negative


def recency_weight(published_at: datetime | None, reference_ts: datetime) -> float:
    """Exponential recency weight; missing timestamps get full weight."""
    if published_at is None:
        return 1.0
    age_days = max(0.0, (reference_ts - published_at).total_seconds() / 86400.0)
    return 0.5 ** (age_days / HALF_LIFE_DAYS)


def _population_std(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    return (sum((v - mean) ** 2 for v in values) / len(values)) ** 0.5


def aggregate(
    scored_articles: list[dict],
) -> dict:
    """Deterministically aggregate scored articles.

    Each item: {"article_id", "published_at" (datetime|None), "label"
    ("positive"|"neutral"|"negative"), "positive", "neutral", "negative",
    "model_confidence"}.

    Returns {} when the list is empty; otherwise:
    {
        "score": float 0-100,
        "weighted_mean_polarity": float,
        "distribution": {"positive": w, "neutral": w, "negative": w},
        "confidence_components": {"coverage", "model_confidence",
                                  "consistency", "recency"},
        "confidence": float 0-1,
        "article_count": int,
        "reference_ts": datetime,
    }
    """
    if not scored_articles:
        return {}

    # Reference timestamp = latest published_at in the analyzed set
    # (data-anchored, deterministic; articles without timestamps sort as
    # oldest-unknown but receive full weight).
    timestamps = [a["published_at"] for a in scored_articles if a.get("published_at")]
    reference_ts = max(timestamps) if timestamps else datetime.now().astimezone()

    weights: list[float] = []
    polarities: list[float] = []
    label_weights = {"positive": 0.0, "neutral": 0.0, "negative": 0.0}
    model_confidences: list[float] = []

    for a in scored_articles:
        w = recency_weight(a.get("published_at"), reference_ts)
        weights.append(w)
        polarities.append(polarity_score(a.get("positive", 0.0), a.get("negative", 0.0)))
        label = a.get("label", "neutral")
        if label not in label_weights:
            label = "neutral"
        label_weights[label] += w
        model_confidences.append(float(a.get("model_confidence", 0.0)))

    total_weight = sum(weights)
    if total_weight <= 0:
        total_weight = 1.0
        weights = [1.0] * len(weights)
        label_weights = {k: v + 1.0 / len(weights) for k, v in label_weights.items()}

    weighted_mean_polarity = sum(w * p for w, p in zip(weights, polarities)) / total_weight
    score = (weighted_mean_polarity + 1.0) / 2.0 * 100.0

    distribution = {k: v / total_weight for k, v in label_weights.items()}

    coverage = min(1.0, len(scored_articles) / FULL_COVERAGE_ARTICLES)
    mean_model_confidence = sum(model_confidences) / len(model_confidences)
    consistency = max(0.0, min(1.0, 1.0 - _population_std(polarities)))
    half_life_seconds = HALF_LIFE_DAYS * 86400.0
    fresh_weight = sum(
        w for w, a in zip(weights, scored_articles)
        if a.get("published_at") is None
        or (reference_ts - a["published_at"]).total_seconds() <= half_life_seconds
    )
    recency = fresh_weight / total_weight

    components = {
        "coverage": round(coverage, 4),
        "model_confidence": round(mean_model_confidence, 4),
        "consistency": round(consistency, 4),
        "recency": round(recency, 4),
    }
    confidence = sum(
        components[k] * CONFIDENCE_WEIGHTS[k] for k in CONFIDENCE_WEIGHTS
    )

    return {
        "score": round(max(0.0, min(100.0, score)), 1),
        "weighted_mean_polarity": round(weighted_mean_polarity, 4),
        "distribution": {
            "positive": round(distribution["positive"], 4),
            "neutral": round(distribution["neutral"], 4),
            "negative": round(distribution["negative"], 4),
        },
        "confidence_components": components,
        "confidence": round(max(0.0, min(1.0, confidence)), 2),
        "article_count": len(scored_articles),
        "reference_ts": reference_ts,
    }