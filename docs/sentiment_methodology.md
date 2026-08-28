# Sentiment Analyst — Methodology

> Implementation: `backend/app/agents/sentiment/`
> (`methodology.py`, `sentiment_agent.py`, `model.py`)
> Version: `sentiment_analyst_v1` (recorded in every output's `provenance`)

## Purpose

The Sentiment Analyst answers:

> "What does recent, relevant news sentiment say about the company?"

It scores stored news articles with a **local** financial sentiment model
(FinBERT — no paid LLM API) and aggregates them deterministically into the
standardized `AgentOutput`.

## Pipeline

```
stored articles (NewsRepository, DuckDB)
    → relevance filter (entity name substring OR symbol whole-word match)
    → text preparation (title + description, whitespace-collapsed)
    → FinBERT inference (local, eval mode, no sampling)
    → per-article polarity = P(positive) − P(negative)   ∈ [−1, +1]
    → recency-weighted aggregation (data-anchored, deterministic)
    → composite score 0–100 + confidence + label distribution
    → standardized AgentOutput
```

The agent consumes **only** stored canonical articles via `NewsRepository` —
it is never coupled to NewsAPI or any provider. The model is **injected**
(`FinBERTSentimentModel` in production; fakes in tests).

## News ingestion (upstream)

- Provider: `NewsAPINewsProvider` (`app/data/providers/news/newsapi_provider.py`),
  implementing the `NewsProvider` contract — replaceable.
- API key comes **only** from the `NEWS_API_KEY` environment variable
  (via `Settings`). It is never hardcoded.
- Missing key → provider reports itself unconfigured; `NewsService` returns
  explicit `UNAVAILABLE` status. The backend starts and all unrelated modules
  keep working. No articles are ever fabricated.
- HTTP 401/403 → `ProviderUnavailableError`; 429 → rate-limit `ProviderError`;
  network/other failures → `ProviderError`. All surface as explicit
  UNAVAILABLE/ERROR statuses, never crashes.
- Duplicate detection: `article_id` = SHA-256 of the canonical article URL
  (fallback: SHA-256 of `title|publishedAt` when URL is missing). Re-fetched
  duplicates are skipped at storage; `content_hash` (SHA-256 of
  `title|description|content`) is kept for audit.

## Recency weighting (time-aware, deterministic)

Each relevant article gets weight

```
w_i = 0.5 ** (age_days_i / 7)        # HALF_LIFE_DAYS = 7
```

`age_days_i` is measured against `reference_ts` = the **latest published_at
among the analyzed articles** — not the wall clock. Re-running on the same
stored data therefore produces byte-identical results. Articles without a
timestamp receive full weight and are flagged in `data_limitations`.

## Composite score

```
weighted_mean_polarity = Σ(w_i × polarity_i) / Σ w_i      ∈ [−1, +1]
score                  = (weighted_mean_polarity + 1) / 2 × 100   ∈ [0, 100]
```

Label distribution = normalized weight share per predicted label
(positive + neutral + negative = 1).

## Confidence (documented components)

```
confidence = 0.35 × coverage + 0.25 × model_confidence
           + 0.25 × consistency + 0.15 × recency
```

| component | definition |
|---|---|
| coverage | `min(1, n_relevant / 10)` — 10 relevant articles = full coverage |
| model_confidence | mean predicted-label probability across articles |
| consistency | `1 − population std-dev(polarities)`, clamped to [0, 1] |
| recency | weight share of articles within one half-life (7 days) of the reference |

No randomness anywhere. Empty input → `score = None`, `confidence = 0`.

## Status semantics (honest degradation)

| situation | status | score |
|---|---|---|
| no stored articles | UNAVAILABLE | None |
| stored articles but none mention the entity | UNAVAILABLE | None |
| sentiment model unavailable / load / inference failure | UNAVAILABLE | None |
| 1–2 relevant articles (thin evidence) | DEGRADED | computed |
| ≥ 3 relevant articles | OK | computed |

The backend **never crashes** because of a model problem — failures are
converted into explicit UNAVAILABLE outputs with limitations.

## Output contents

- `score`, `signal` (shared `signal_from_score` mapping), `confidence`
- factors: `news_volume`, `model_confidence`, `sentiment_consistency`, `recency`
  (each with value + human-readable detail)
- evidence: up to 5 relevant articles (id, source, timestamp, title/URL)
- rationale: deterministic summary with distribution
- limitations: coverage, missing timestamps, thin evidence, model/language
  caveats, "not investment advice"
- provenance: methodology version, model id, article counts, reference
  timestamp, weighted mean polarity, confidence components

Per-article `SentimentResult`s (label + 3 probabilities + model id +
confidence) are persisted to the `sentiment_results` table.

## Known limitations

- FinBERT is trained on English financial text; non-English or garbled text
  may score unreliably (flagged in limitations).
- Relevance matching is lexical (name/symbol); it may miss articles that
  refer to the company only indirectly (e.g. "Tata group IT arm").
- NewsAPI free tiers cap history (~30 days) and volume; coverage depends on
  the configured plan.
- Sentiment reflects news tone only — it is not investment advice and
  excludes fundamentals, price action, and macro factors.