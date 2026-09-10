# FinCortext — Architecture

## 1. Design goals

1. **Source-agnostic agents.** Analyst agents consume canonical FinCortext domain
   data through repositories/services — never external providers or websites.
2. **Replaceable providers.** Every external data source (yfinance, NewsAPI,
   future licensed feeds) sits behind a narrow provider interface.
3. **Deterministic, explainable intelligence.** Agent scores are computed by
   documented, testable formulas — no random numbers, no LLM-invented conclusions.
4. **Provenance and point-in-time correctness.** Every stored observation records
   where it came from and when it became available, so future backtests can
   distinguish *financial period end* from *public availability*.
5. **Honest degradation.** Missing keys, provider outages, or unavailable models
   produce explicit statuses (LIVE / CACHED / IMPORTED OFFICIAL / SAMPLE /
   UNAVAILABLE / ERROR) — never silently substituted data.

## 2. Module boundaries

```
backend/app/
├── core/          config, logging, exceptions (no business logic)
├── domain/
│   ├── models/    canonical Pydantic domain models
│   └── contracts/ provider interfaces + AgentOutput contract
├── data/
│   ├── providers/    adapters: market/ (yfinance), fundamentals/, news/ (NewsAPI)
│   ├── ingestion/    file import: filings (CSV/XBRL/XML/PDF-limited)
│   ├── validation/   schema + sanity validation per data type
│   ├── normalization/ raw → canonical mapping
│   ├── storage/      DuckDB connection + schema
│   └── universe/     versioned stock universe configuration
├── repositories/  typed read/write access to DuckDB (agents use these)
├── agents/
│   ├── base/       shared agent interface + AgentOutput builder
│   ├── firm/       Firm Analyst (deterministic)
│   ├── industry/   Industry Analyst (deterministic)
│   └── sentiment/  Sentiment Analyst (local FinBERT + deterministic aggregation)
├── services/      orchestration used by API routes (no logic in routes)
└── api/routes/    thin FastAPI route modules by domain
```

**Rule:** route handlers only parse requests, call services, and shape responses.
Business logic lives in services/agents/repositories.

## 3. Data flow

```
┌──────────────────────────── DATA SOURCES ───────────────────────────┐
│ yfinance (market)   NewsAPI (news)   Official filings (CSV/XBRL/PDF) │
│ Future: licensed fundamentals, RSS/GDELT, industry reports           │
└──────────────────────────────┬──────────────────────────────────────┘
                               ↓ provider adapters / file import
┌──────────────────────────── DATA PIPELINE ──────────────────────────┐
│ ingestion → validation → normalization → feature/metric calculation  │
└──────────────────────────────┬──────────────────────────────────────┘
                               ↓
┌──────────────────────── DUCKDB STORAGE ─────────────────────────────┐
│ market_prices · universe_metadata · financial_observations ·         │
│ filing_documents · news_articles · sentiment_results ·               │
│ agent_outputs · data_provenance                                      │
└──────────────────────────────┬──────────────────────────────────────┘
                               ↓ repositories (source-agnostic reads)
┌──────────────────────────── AGENT LAYER ────────────────────────────┐
│ Firm Analyst    Industry Analyst    Sentiment Analyst                │
│ (Macro Analyst + Portfolio Agent: future, consume same contract)     │
└──────────────────────────────┬──────────────────────────────────────┘
                               ↓ standardized AgentOutput
                    FastAPI services/routes → React frontend
                    (future Portfolio Agent consumes AgentOutputs)
```

## 4. Provider abstraction

Conceptual interfaces (see `app/domain/contracts/providers.py`):

- `MarketDataProvider` — `fetch_ohlcv(ticker, start, end) -> list[MarketPrice]`
- `FundamentalDataProvider` — development/fallback enrichment only; ingested
  official filings are the primary source of truth for fundamentals.
- `NewsProvider` — `fetch_articles(query, from, to) -> list[NewsArticle]`

Adapters translate provider-specific quirks (NSE `.NS` suffixes, NewsAPI payload
shapes) into canonical domain models **at the boundary**. Agents never see
provider payloads.

## 5. Storage

DuckDB (single local file, configured via `FINCORTEXT_DB_PATH`) holds both raw
provenance records and normalized canonical tables. Raw/source concepts (filing
documents, provider fetch metadata) are kept separate from normalized data
(market prices, financial observations, news articles). See
[docs/data_model.md](docs/data_model.md) for the physical schema.

## 6. Canonical data contracts

All pipeline stages exchange Pydantic models from `app/domain/models`:
`MarketPrice`, `FinancialObservation`, `NewsArticle`, `SentimentResult`,
`AgentOutput`, plus provenance metadata. Contracts are documented in
[docs/agent_contracts.md](docs/agent_contracts.md) and
[docs/data_model.md](docs/data_model.md).

## 7. Agent architecture

Each agent:

1. Pulls canonical data via repositories (never providers).
2. Computes deterministic factors with documented formulas and weights.
3. Handles missing data by reducing evidence and confidence — never fabricating.
4. Emits the standardized `AgentOutput` (score 0–100, signal, confidence,
   factors, rationale, evidence, limitations, provenance references).
5. Persists its output for history and future Portfolio Agent consumption.

The future Portfolio Agent will consume `AgentOutput`s from all analysts
through the same contract — no hidden agent-to-agent coupling.

### Implemented agents and their data seams

| agent | reads | model/provider coupling |
|---|---|---|
| Firm Analyst | `FinancialRepository` (ingested filings), `MarketRepository` (prices) | none |
| Industry Analyst | `MarketRepository` (peer prices), `FinancialRepository` (peer margins), universe config | none |
| Sentiment Analyst | `NewsRepository` (stored articles) | injectable sentiment model (`FinBERTSentimentModel` in production, fakes in tests) |

Methodology documents: `docs/industry_methodology.md`,
`docs/sentiment_methodology.md`, and the docstrings of
`app/agents/firm/methodology.py`.

### News + sentiment pipeline

```
NewsProvider contract ← NewsAPINewsProvider (key ONLY from NEWS_API_KEY env)
        ↓ canonical NewsArticle (article_id = SHA-256 of URL; content_hash audit)
NewsService (entity association, dedup-on-store, provenance, explicit statuses)
        ↓ DuckDB news_articles
SentimentAgent (relevance filter → FinBERT → polarity → recency-weighted
                aggregation anchored to the latest article timestamp)
        ↓ per-article SentimentResults + standardized AgentOutput
```

Degradation contract: missing `NEWS_API_KEY` → provider reports unconfigured,
`NewsService` returns explicit UNAVAILABLE, the backend starts and all other
modules keep working. Model load/inference failures → `ModelUnavailableError`
→ UNAVAILABLE AgentOutput — the backend never crashes on model problems.

## 8. Frontend architecture

React 18 + TypeScript + Vite (`frontend/`), organized by feature:

```
frontend/src/
├── app/            App shell, flat product nav, FinCortextContext
│                   (session research state), dark theme styles
├── components/      common/ reusable UI (StatusBadge, CompanySelector,
│                    AgentOutputCard, ScoreRing)
├── features/        dashboard/ · data/ (sources, pipeline, market, filings,
│                    quality — internal routes, unlinked from demo nav) ·
│                    agents/ (firm, industry, sentiment, summary) ·
│                    portfolio/ · research/ (future placeholders)
├── services/        api.ts — the ONLY module that talks to the backend
├── types/           api.ts — typed mirrors of backend response contracts
└── utils/           FinCortextLogo.png — product logo asset (header branding)
```

Rules: typed API service layer, feature separation, loading/error/unavailable
states everywhere, explicit data-status badges (LIVE / CACHED / IMPORTED
OFFICIAL / SAMPLE / UNAVAILABLE / ERROR), and honest empty states. The combined
intelligence summary states that portfolio synthesis is reserved for the future
Portfolio Agent.

### Session research state (`app/FinCortextContext.tsx`)

A single `FinCortextProvider` owns the demo's research state so navigation never
destroys it:

- **Company selection** — single source of truth, mirrored to `?symbol=` (links
  stay shareable, header nav carries it across pages) with a `localStorage`
  fallback. The Dashboard and all analyst pages consume the same value.
- **Per-symbol caches** — universe list, price series, agent-output history,
  stored news, and market coverage are fetched once per symbol per session
  (in-flight dedup included). Route changes remount page components but never
  refetch.
- **Run-result cache** — fresh `AgentOutput`s are recorded the moment they are
  produced (and folded into the outputs-history cache), so returning to an
  analyst or the Dashboard shows the previous result with its timestamp instead
  of re-running the model/data pipeline. Only an explicit user action runs an
  analysis or refreshes data.

Historical note: the app shell previously rendered `<main key={location.pathname}>`,
which remounted every page on navigation, while the Dashboard kept its symbol in
local component state — company choice and results were discarded on every route
change and cheap reads re-ran. Both causes are removed; regression tests pin the
no-refetch and cross-page symbol behavior.

### Industry Analyst automatic data preparation

`AgentService` (optionally wired with `MarketService`, default `None` so existing
constructions are unaffected) calls
`MarketService.ensure_history(symbols, min_bars, max_age_days=7)` for the company
and its sector peers before every industry run: sufficient fresh cached history is
reused, only missing/stale symbols go through the normal provider → validation →
storage pipeline, per-symbol provider failures are isolated (recorded as
`refresh_failed`, never raised), and a transparent `data_preparation` summary is
recorded in the output provenance. The `IndustryAgent` itself stays
repository-only — no provider coupling, no architectural drift.

## 9. Future Portfolio Agent integration

Reserved seams (no fake implementations):

- `AgentOutput` contract is already portfolio-ready (entity-scoped, scored,
  confidence-weighted, provenance-linked).
- Universe configuration provides the tradable set.
- Storage schema leaves room for portfolio/optimization tables.
- Frontend Portfolio/Research pages are explicit "Coming soon" placeholders.

A future Portfolio Agent would: read the latest persisted `AgentOutput` per
(agent, entity) from `agent_outputs`, weight scores by confidence and status
(OK/DEGRADED/UNAVAILABLE), apply the future risk/constraint engine, and hand
candidate weights to the future optimizer — all through the existing
contract and repository seams, with no agent-to-agent calls.

## 10. Vision diagram vs implemented scope

`frontend/src/utils/SystemArchitecture.jpeg` is the full-vision overview diagram
(Data Sources → Data Pipeline → Agent Layer → Portfolio Layer → Execution &
Backtesting → Outputs & Interfaces, over a cross-cutting Foundation Layer). It
deliberately shows the destination, not the current build: of its six blocks,
only **1. Data Sources** (market/news/filings adapters), **2. Data Pipeline**,
the **Firm / Industry / Sentiment** agents of 3. Agent Layer, the **Agent Outputs**
contract, and **6. Web Dashboard + APIs** are implemented. Macro Analyst,
Portfolio Layer, Execution & Backtesting, and the remaining interfaces are future
placeholders. The asset lives next to the product logo in `frontend/src/utils/`
because it is a product/vision asset, not a code module — normative technical
documentation stays in this file, `README.md`, and `docs/`.
