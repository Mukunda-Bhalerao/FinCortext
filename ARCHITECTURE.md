# FinCortext — Architecture

## 1. Design goals

1. **Source-agnostic agents.** Analyst agents consume canonical FinCortext domain
   data through repositories/services — never external providers or websites.
2. **Replaceable providers.** Every external data source (Upstox, NewsAPI,
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
│   ├── providers/    adapters: market/ (Upstox), fundamentals/ (unwired seam), news/ (NewsAPI)
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
│   ├── macro/      Macro Analyst (deterministic, own MacroOutput contract)
│   └── sentiment/  Sentiment Analyst (local FinBERT + deterministic aggregation)
├── services/      orchestration used by API routes (no logic in routes)
└── api/routes/    thin FastAPI route modules by domain
```

**Rule:** route handlers only parse requests, call services, and shape responses.
Business logic lives in services/agents/repositories.

## 3. Data flow

```
┌──────────────────────────── DATA SOURCES ───────────────────────────┐
│ Upstox (market + gauges)           NewsAPI (news)                     │
│ Official filings (CSV/XBRL/PDF) · curated macro (RBI/MoSPI releases) │
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
│ agent_outputs · macro_observations · macro_outputs · data_provenance │
└──────────────────────────────┬──────────────────────────────────────┘
                                ↓ repositories (source-agnostic reads)
┌──────────────────────────── AGENT LAYER ────────────────────────────┐
│ Firm · Industry · Sentiment Analysts (AgentOutput contract)          │
│ Macro Analyst (market-wide, dedicated MacroOutput contract)          │
│ (Portfolio Agent: future, consumes same contracts)                    │
└──────────────────────────────┬──────────────────────────────────────┘
                                ↓ AgentOutput / MacroOutput
                     FastAPI services/routes → React frontend
                     (future Portfolio Agent consumes AgentOutputs)
```

## 4. Provider abstraction

Conceptual interfaces (see `app/domain/contracts/providers.py`):

- `MarketDataProvider` — `fetch_ohlcv(ticker, start, end) -> list[MarketPrice]`
- `FundamentalDataProvider` — fallback enrichment only; ingested
  official filings are the primary source of truth for fundamentals.
  No provider is wired in production after the Upstox consolidation:
  refreshes report UNAVAILABLE honestly and stored pre-consolidation
  observations (relabeled `legacy_import`) remain usable. The seam stays
  at the provider boundary for future licensed feeds; `FundamentalsService`
  labels any wired provider's snapshot per symbol (scoped replace).
- `NewsProvider` — `fetch_articles(query, from, to) -> list[NewsArticle]`
- `ResearchProvider` — grounded web research ONLY (`research_company`,
  `suggest_peers`, `research_news`). Never market data, never scores.
  Implemented by `GeminiResearchProvider` on the official `google-genai` SDK
  (`genai.Client(api_key=...)`, JSON-schema responses, `google_search` tool;
  key never in URLs/logs/errors). Failure diagnostics distinguish invalid key,
  retired model (names `GEMINI_MODEL`), rate limit, endpoint error, timeout,
  and safety blocks. `verify_model()` proves generation health with a minimal
  prompt (metadata lookup alone is insufficient). Consumed exclusively by
  `ResearchService`/`CompanyPreparationService`; evidence persists in
  `research_reports`, never as articles or prices.

Adapters translate provider-specific quirks (NSE `.NS` suffixes, NewsAPI payload
shapes) into canonical domain models **at the boundary**. Agents never see
provider payloads.

**Responsibility split (load-bearing):** Upstox → market truth (prices, OHLCV,
instrument resolution, peer market data) and market gauges (India VIX index
candles). Structured providers (filings,
NewsAPI) → financial/fundamental/news truth. FinBERT → news
sentiment. Gemini + Search grounding → research/enrichment (classification,
peer discovery, context, evidence). Deterministic code → all calculations,
scores, risk, constraints, optimization, backtesting. Gemini never prices,
never scores, never overrides deterministic logic.

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
| Firm Analyst | `FinancialRepository` (filings + provider fundamentals), `MarketRepository` (prices) | none |
| Industry Analyst | `MarketRepository` (peer prices), `FinancialRepository` (peer margins), universe config | none |
| Sentiment Analyst | `NewsRepository` (stored articles) | injectable sentiment model (`FinBERTSentimentModel` in production, fakes in tests) |
| Macro Analyst | `MacroRepository` (market-wide indicator series) | none (fully deterministic; no LLM) |

Methodology documents: `docs/industry_methodology.md`,
`docs/sentiment_methodology.md`, `docs/macro_methodology.md`, and the docstrings of
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

### Macro pipeline

```
Curated official CSVs (data/macro/, RBI/MoSPI releases, per-row provenance)
        ↓ CuratedMacroProvider (schema-checked, deterministic observation ids)
Market gauges (India VIX index candles; USD/INR, Brent, US 10Y unavailable —
        no NSE listing on Upstox, reported honestly)
        ↓ UpstoxGaugeProvider (existing Upstox client, no new deps)
MacroService (per-indicator isolation, provenance, explicit statuses)
        ↓ DuckDB macro_observations (point-in-time: period vs published_at)
MacroAgent (7 deterministic factors → majority-vote environment signal + 0–100 environment score)
        ↓ macro_outputs (MacroOutput: POSITIVE/NEUTRAL/NEGATIVE + Macro Environment Score)
```

The Macro Analyst is market-wide: reads carry indicator keys, never symbols,
so company switching cannot misattribute anything. Runs go through the
standard `POST /api/agents/macro/{symbol}/run` route (symbol validated as
request context, recorded in provenance, otherwise ignored); reads use
`GET /api/macro/latest|history|indicators|series/{id}`. The `MacroOutput`
contract is separate from `AgentOutput` on purpose — environment signals must
never read as stock recommendations and must never be blended into one.
The 0–100 Macro Environment Score is a linear rescaling of the same
available-factor vote (always agreeing with the signal); it describes the
environment only, never a company score to blend.

## 8. Frontend architecture

React 18 + TypeScript + Vite (`frontend/`), organized by feature:

```
frontend/src/
├── app/            Sidebar + topbar shell, FinCortextContext
│                   (session research state), dark theme styles
├── components/      common/ reusable UI (StatusBadge, CompanySelector search,
│                    AgentOutputCard, PeerTable)
├── features/        dashboard/ (market overview + macro strip) · company/ (Company Analysis:
│                    priceStats, peer-quote/news/filings hooks, overview page) ·
│                    data/ (sources, pipeline, market, filings,
│                    quality — internal routes, unlinked from demo nav) ·
│                    agents/ (firm, industry, macro, sentiment, summary) ·
│                    portfolio/ (synthesis page) · research/ (future placeholders)
├── services/        api.ts — the ONLY module that talks to the backend
├── types/           api.ts — typed mirrors of backend response contracts
└── utils/           FinCortextLogo.png — product logo asset (sidebar branding)
```

Rules: typed API service layer, feature separation, loading/error/unavailable
states everywhere, explicit data-status badges (LIVE / CACHED / IMPORTED
OFFICIAL / SAMPLE / UNAVAILABLE / ERROR), and honest empty states. One global
company search in the topbar feeds every page; analyst pages carry no selector
of their own. The combined intelligence summary shows the four views side by
side; the Portfolio Synthesis page explains how they fit together without
blending them.

Page responsibilities: Dashboard = market overview (price action, stored
history chart, sector peers with real quotes, compact stored intelligence,
news, derived takeaway). Company Analysis = company details (stored price
statistics, data inventory, analyst run history, peers). Analyst pages = full
methodology, factors, evidence, limitations. Shared derivations live in
`features/company/` (pure `priceStats`, `usePeerQuotes`, `useFilingsCount`).

### Session research state (`app/FinCortextContext.tsx`)

A single `FinCortextProvider` owns the demo's research state so navigation never
destroys it:

- **Company selection** — single source of truth, mirrored to `?symbol=` (links
  stay shareable, sidebar nav carries it across pages) with a `localStorage`
  fallback. One global search in the topbar feeds every page.
- **Per-symbol caches** — universe list, price series, agent-output history,
  stored news, and market coverage are fetched once per symbol per session
  (in-flight dedup plus ref mirrors, so stale closures after rapid symbol
  switches can never duplicate a settled fetch). Route changes remount page
  components but never refetch.
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

## 9. Portfolio Agent (Central Orchestrator) integration

Implemented synthesis layer (no scoring, no blending):

- `AgentOutput` + `MacroOutput` contracts are portfolio-ready (entity-scoped,
  scored, confidence-weighted, provenance-linked).
- `PortfolioAgent` (`app/agents/portfolio/`) reads the four analyst outputs
  for ONE company and explains how they fit together (agreement/conflicts,
  thesis, evidence, risks, scenarios, coverage) — deterministic, no overall
  score, no overall signal, no averaging.
- `AgentService.run_portfolio` runs all four analysts for the symbol (each
  persists its own output), then synthesizes; route
  `POST /api/agents/portfolio/{symbol}/run`, reads via `/api/portfolio/*`.
- Macro stays market-wide inside the synthesis (same environment view for
  every company, labeled as context, never a stock call).
- Frontend Portfolio Synthesis page (`/portfolio`) renders the stored view;
  Dashboard stays concise (compact scores + link). Weight optimization,
  risk engine execution and backtesting remain future placeholders.

A future optimizer would: weight scores by confidence and status
(OK/DEGRADED/UNAVAILABLE), apply the future risk/constraint engine, and hand
candidate weights to the future optimizer — all through the existing
contract and repository seams, with no agent-to-agent calls.

## 10. Vision diagram vs implemented scope

`frontend/src/utils/SystemArchitecture.jpeg` is the full-vision overview diagram
(Data Sources → Data Pipeline → Agent Layer → Portfolio Layer → Execution &
Backtesting → Outputs & Interfaces, over a cross-cutting Foundation Layer). It
deliberately shows the destination, not the current build: of its six blocks,
only **1. Data Sources** (market/news/filings/macro adapters), **2. Data Pipeline**,
the **Firm / Industry / Sentiment / Macro** agents of 3. Agent Layer, the Portfolio
synthesis layer, the **Agent Outputs**
(+ Macro Outputs + Portfolio Views) contract, and **6. Web Dashboard + APIs** are implemented. Execution & Backtesting, and the remaining interfaces are future
placeholders. The asset lives next to the product logo in `frontend/src/utils/`
because it is a product/vision asset, not a code module — normative technical
documentation stays in this file, `README.md`, and `docs/`.
