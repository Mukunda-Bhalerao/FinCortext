# Sentiment Analyst — Methodology

> Implementation: `backend/app/agents/sentiment/`
> (`methodology.py`, `sentiment_agent.py`, `model.py`, `relevance.py`)
> Version: `sentiment_analyst_v1` (recorded in every output's `provenance`)

## Purpose

The Sentiment Analyst answers:

> "What does recent, relevant news sentiment say about the company?"

It scores stored news articles with a **local** financial sentiment model
(FinBERT — no paid LLM API) and aggregates them deterministically into the
standardized `AgentOutput`.

## Relevance screening (financial relevance, not keyword hits)

Provider search (`"Company Name" OR SYMBOL`) returns anything that merely
mentions the ticker — sponsored marathons, HR anecdotes, tragedies, market
digests, even common-noun collisions ("weighing reliance on Stripe"). Scoring
those as company sentiment would fabricate signal from noise, so every stored
article passes a deterministic two-gate screen (`relevance.py`) before it can
influence the score. An article is **relevant** only if it has BOTH:

1. **Company identity** — the full legal name (substring) or a curated alias /
   ticker from the universe entry. Single-token identifiers match whole-word
   only (`TCS` never fires inside "switches"); tokens shorter than 3
   characters never bare-match (`LT` would collide constantly — only `L&T`
   or the full name identifies Larsen & Toubro); bare forms that collide with
   ordinary words stay out of `aliases` (documented per company in
   `universe_config.py`), except case-sensitive brand tokens in
   `strict_aliases` (capitalized `Reliance` = the company, lowercase
   `reliance` = the common noun).
2. **Financial/business context** — at least one term from the documented
   `FINANCIAL_KEYWORDS` set (earnings & results, corporate actions, leadership
   & workforce, market action & analyst views, regulatory/legal, money),
   matched whole-word over title + description.

And never when it is about an **excluded topic** (`EXCLUDED_TOPICS` plus
`EXCLUDED_PATTERNS`): brand-run sport/sponsorship events (marathons, cricket,
golf, sponsorships), personal tragedies/accidents, and retail-discount flyers
where a promo acronym collides with the ticker (Harbor Freight's "Inside
Track Club" sales vs bare `ITC`) — a ticker mention there carries no
investment signal. Exclusion wins over everything else.

Consequences, all honest: a sponsored-marathon article, a career anecdote
("From TCS to Microsoft…"), an employee tragedy, or a market digest that never
names the company is rejected; an earnings beat, an order win, a leadership
change, or a sector rally that names the company is kept. Every verdict
carries a machine-readable reason (`relevant` / `no_identity` /
`no_financial_context` / `excluded_topic`); the output reports
`articles_stored` / `articles_relevant` / `articles_rejected` plus the
per-reason breakdown in provenance, names up to two excluded examples in
limitations, and the `news_volume` factor details the same counts. If nothing
relevant remains, the result is UNAVAILABLE — nothing is scored from noise.

Retrieval favors recall so the screen has material to work with: the default
NewsAPI query is built from the legal name plus curated aliases
(`default_news_query` in `news_service.py`), not just name-or-symbol.

## Pipeline

```
stored articles (NewsRepository, DuckDB)
    → relevance screen (identity AND financial context, minus excluded topics)
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
| stored articles but none relevant (no mention, no financial context, or excluded topics) | UNAVAILABLE | None |
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
- provenance: methodology version, model id, article counts
  (stored / relevant / rejected + per-reason breakdown), reference
  timestamp, latest analyzed article date, weighted mean polarity,
  confidence components

Per-article `SentimentResult`s (label + 3 probabilities + model id +
confidence) are persisted to the `sentiment_results` table.

## Known limitations

- FinBERT is trained on English financial text; non-English or garbled text
  may score unreliably (flagged in limitations).
- Relevance screening is lexical (identifiers + business vocabulary); it may
  miss articles that refer to the company only indirectly (e.g. "Tata group
  IT arm"), and bare short brand tokens ("Reliance" headlines without other
  identifiers) match case-sensitively by design — documented trade-offs in
  `relevance.py` / `universe_config.py`.
- NewsAPI free tiers cap history (~30 days) and volume; coverage depends on
  the configured plan.
- Sentiment reflects news tone only — it is not investment advice and
  excludes fundamentals, price action, and macro factors.