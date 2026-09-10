# FinCortext

**Investment intelligence research platform — fundamentals, industry position, and news sentiment, with the evidence attached.**

FinCortext reads a listed company from three independent angles — a Firm Analyst (fundamentals + market
behavior), an Industry Analyst (peer and sector-relative position), and a Sentiment Analyst (financial-news
tone) — and shows the views side by side with the data behind each one. Every score carries its factors,
rationale, evidence references, limitations, and provenance. Missing data is reported honestly; nothing is
fabricated to fill a gap.

---

## 1. What FinCortext is

A research-oriented financial intelligence platform for Indian NSE large-caps. It ingests market prices,
official filing data, and financial news through replaceable provider adapters, normalizes them into
canonical domain data stored in DuckDB, and runs deterministic analyst agents whose standardized outputs
are designed to be consumed by a future Portfolio Agent.

The current demo covers the **Data → Intelligence** half of the vision
(Data → Intelligence → Decision → Optimization → Evaluation). Decision, optimization, and evaluation
layers are explicitly future work.

## 2. Problem being addressed

Retail-grade research tooling typically gives you either raw prices with no interpretation, or opaque
scores with no evidence. FinCortext targets the middle: every analytical claim must be traceable to the
stored data it was computed from, and every gap in the data must be visible as a gap — not silently
papered over.

## 3. Project objective

Build a working, testable foundation for explainable investment intelligence:

1. Canonical data layer with provenance and point-in-time correctness.
2. Deterministic analyst agents with documented methodologies.
3. A standardized output contract (`AgentOutput`) that a future Portfolio Agent can consume.
4. A demo frontend that reads like a research product, not an admin console.

## 4. Current scope

**IMPLEMENTED (working, tested):**

- Configuration, structured logging with secret redaction, domain exception hierarchy, `GET /health`.
- Canonical domain models + standardized `AgentOutput` contract (`OK` / `DEGRADED` / `UNAVAILABLE`).
- DuckDB analytical storage with provenance log and point-in-time metadata.
- Versioned 10-symbol NSE large-cap universe with sector/industry metadata.
- Market data pipeline: yfinance adapter → validation → normalization → DuckDB → API.
- Official filing ingestion: CSV / XBRL / XML parsers + limited PDF fallback, content-hash dedup.
- **Firm Analyst** — fundamental/valuation/momentum scoring.
- **Industry Analyst** — peer-group and sector-relative scoring, with automatic market-data preparation.
- **News + Sentiment pipeline** — NewsAPI provider, local FinBERT model, deterministic time-aware aggregation.
- React + TypeScript research frontend (Dashboard, three analysts, Combined Summary) with explicit
  data-status labels (`LIVE` / `CACHED` / `IMPORTED OFFICIAL` / `SAMPLE` / `UNAVAILABLE` / `ERROR`).
- Session-wide frontend research state: company selection and results survive navigation without
  re-running analyses.

**PARTIALLY IMPLEMENTED:**

- PDF filing parsing (basic text-extraction fallback only — documented as unreliable for arbitrary reports).
- Sample-data support (served only on explicit request, never silently substituted).

**FUTURE (explicit placeholders, not implemented):**

- Macro Analyst, Portfolio Agent / orchestration, risk & constraint engine, portfolio optimization,
  backtesting, performance evaluation, scenario/stress testing, explainability module beyond
  per-agent rationale/evidence, authentication, deployment infrastructure, licensed data providers.

## 5. Core design philosophy

1. **Source-agnostic agents.** Analysts consume canonical domain data through repositories/services —
   never external providers or websites.
2. **Replaceable providers.** Every external source sits behind a narrow interface
   (`MarketDataProvider`, `FundamentalDataProvider`, `NewsProvider`).
3. **Deterministic intelligence.** Scores come from documented, testable formulas — no randomness, no
   invented conclusions.
4. **Provenance and point-in-time correctness.** Every observation records where it came from and when
   it became available (`period_end` vs `available_at`), so future backtests stay honest.
5. **Honest degradation.** Missing keys, provider outages, or unavailable models produce explicit
   statuses — never silently substituted data.

## 6. System architecture

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full description. In brief:

```
Data Sources (yfinance | NewsAPI | official filings | fixtures)
        ↓  provider adapters (replaceable interfaces)
Data Pipeline (ingestion → validation → normalization → storage)
        ↓
DuckDB canonical storage (+ provenance, point-in-time metadata)
        ↓  repositories / services (source-agnostic)
Agent Layer (Firm Analyst | Industry Analyst | Sentiment Analyst)
        ↓  standardized AgentOutput contract
FastAPI services/routes  →  React frontend   …   future Portfolio Agent
```

Agents never call external providers directly; data acquisition lives in provider/service layers.
Route handlers only parse requests, call services, and shape responses.

## 7. Data → Intelligence flow

1. **Acquire** — provider adapters fetch market/news data; filing files are uploaded and parsed.
2. **Validate & normalize** — sanity checks (positive prices, high ≥ low, dedup); raw payloads become
   canonical Pydantic models at the boundary.
3. **Store** — DuckDB tables hold normalized observations plus provenance events.
4. **Analyze** — agents read repositories only, compute deterministic factors, emit `AgentOutput`.
5. **Persist & present** — outputs are stored (`agent_outputs`) and served to the frontend, which shows
   scores together with evidence and limitations.

## 8. Backend architecture

```
backend/app/
├── core/          config (env/.env, no hardcoded secrets), logging, exceptions
├── domain/
│   ├── models/    MarketPrice, FinancialObservation, FilingDocument,
│   │              NewsArticle, SentimentResult, UniverseEntry, Provenance,
│   │              DataStatus / DataSourceType enums
│   └── contracts/ provider interfaces + AgentOutput contract
├── data/
│   ├── providers/    market/ (yfinance), fundamentals/ (fallback), news/ (NewsAPI)
│   ├── ingestion/    filings (CSV/XBRL/XML/PDF-limited)
│   ├── validation/   per-type sanity checks; rejections reported with reasons
│   ├── storage/      DuckDB connection + schema
│   └── universe/     versioned stock universe configuration
├── repositories/  typed DuckDB access (market, financial, news, filings,
│                  agent_output, universe mirror, provenance log)
├── agents/
│   ├── base/       shared agent interface + AgentOutput builder
│   ├── firm/       Firm Analyst (+ documented methodology module)
│   ├── industry/   Industry Analyst (+ documented methodology module)
│   └── sentiment/  Sentiment Analyst (injectable model + methodology module)
├── services/      MarketService, FilingService, NewsService, AgentService,
│                  composition-root container
└── api/routes/    thin FastAPI modules: health, universe, market, filings,
                   news, agents
```

## 9. Frontend architecture

React 18 + TypeScript + Vite, organized by feature:

```
frontend/src/
├── app/            Sidebar + topbar shell, FinCortextContext
│                   (session research state), dark theme styles
├── components/     common/ reusable UI (StatusBadge, CompanySelector search,
│                   AgentOutputCard, PeerTable)
├── features/       dashboard/ (market overview) · company/ (Company Analysis:
│                   priceStats, peer-quote/news/filings hooks, overview page) ·
│                   data/ (sources, pipeline, market, filings,
│                   quality — internal routes, unlinked from demo nav) ·
│                   agents/ (firm, industry, sentiment, summary) ·
│                   portfolio/ · research/ (future placeholders)
├── services/       api.ts — the ONLY module that talks to the backend
├── types/          api.ts — typed mirrors of backend response contracts
└── utils/          FinCortextLogo.png (real product logo, used in the sidebar)
```

Rules: typed API service layer, feature separation, loading/error/unavailable states everywhere,
explicit data-status badges, honest empty states. One global company search in the topbar feeds
every page; the selection is mirrored to `?symbol=` so links stay shareable, cached per symbol
for the session, and persisted to `localStorage` as a fallback.
Navigating between pages never refetches cached reads and never re-runs analyses; fresh results are
recorded into the session cache (and the outputs-history cache) the moment they are produced.

## 10. Data providers

| Source | Adapter | Notes |
|---|---|---|
| Market prices | `YFinanceMarketProvider` (yfinance) | NSE `.NS` ticker mapping from universe config; all failures wrapped as `ProviderError`. Canonical storage key is always the internal symbol (`TCS`), never the provider ticker (`TCS.NS`). |
| News | `NewsAPINewsProvider` (NewsAPI) | Key **only** from `NEWS_API_KEY`; missing key → graceful `UNAVAILABLE`, never a crash. 401/403 → unavailable, 429 → rate-limit error. |
| Fundamentals | Ingested official filings (primary truth) + provider annual statements (fallback) | `YFinanceFundamentalsProvider` implements the `FundamentalDataProvider` seam: annual income/balance rows with real fiscal periods plus snapshot P/E + ROE. Stored as `source_type=yfinance`, never as official filings. |
| Future | Licensed feeds, RSS/GDELT, industry reports | Seams reserved at the provider boundary. |

## 11. Market data pipeline

`MarketService.refresh_symbol` → provider fetch → validation (positive prices, high ≥ low,
open/close within range, duplicates) → normalization → DuckDB → provenance event → API
(`POST /api/market/refresh[/{symbol}]`, `GET /api/market/prices/{symbol}` with
`LIVE`/`CACHED`/`UNAVAILABLE` status, `GET /api/market/status` for universe-wide coverage).
Per-symbol failure isolation: one bad symbol never blocks the rest of the universe.

## 12. News pipeline

Provider fetch → canonical `NewsArticle` (stable `article_id` = SHA-256 of URL, `content_hash` audit
hash, source metadata, publication/collection timestamps) → `NewsService` entity association +
dedup-on-store + provenance → DuckDB → API (`GET /api/news/status`,
`POST /api/news/refresh/{symbol}`, `GET /api/news/{symbol}`). Missing key degrades gracefully; the
backend and all unrelated modules keep working.

## 13. Firm Analyst

Deterministic scoring over 6 documented factors — profitability 0.25, revenue growth 0.20, financial
health 0.20, return on equity 0.15, valuation 0.10, market momentum 0.10 — with linear score bounds,
weight redistribution for missing factors, and confidence = coverage × quality tier. Consumes
`FinancialRepository` (ingested filings = primary truth, provider annual statements = labeled
fallback) + `MarketRepository` (90-day momentum). Each metric uses its own latest observation, so
mixed-vintage data never silently drops a factor. Methodology: `backend/app/agents/firm/methodology.py`.

## 14. Industry Analyst

Deterministic scoring over 4 documented factors — peer momentum 0.30, relative strength 0.30,
peer fundamentals 0.25, sector volatility 0.15 — with median-based peer stats (company excluded from
peer medians) and a documented volatility convention (simple daily returns, population std-dev,
× √252). Peer grouping comes from the versioned universe config. Methodology:
[docs/industry_methodology.md](docs/industry_methodology.md).

## 15. Sentiment Analyst

Deterministic financial-relevance screen (`relevance.py`: company identity AND
financial/business context required, brand-sport/tragedy/retail-promo topics
excluded, former-affiliation bio-lines disqualified; stored/relevant/rejected
counts with per-reason breakdown in every output) → local FinBERT
(ProsusAI/finbert default, configurable; lazy-loaded, ~440 MB first download)
→ polarity P(pos) − P(neg) → recency-weighted aggregation with 7-day
half-life anchored to the latest article timestamp → composite 0–100 score with confidence =
0.35·coverage + 0.25·model_confidence + 0.25·consistency + 0.15·recency. Model load/inference
failures → explicit `UNAVAILABLE`, never a crash. Methodology:
[docs/sentiment_methodology.md](docs/sentiment_methodology.md).

## 16. Combined Summary

Runs the three analysts for one company and shows their standardized scores side by side. Each
analyst is independent — they share only the `AgentOutput` contract. **No blending into a single
score, no recommendations, no weights**: portfolio synthesis is reserved for the future Portfolio
Agent.

## 17. AgentOutput contract

Every agent emits the same shape (see [docs/agent_contracts.md](docs/agent_contracts.md)):

`agent_id, entity_id, score (0–100 | null), signal (strong_buy … strong_sell | unavailable),
confidence, factors[], rationale, evidence[], data_limitations[], generated_at, data_version,
provenance, status`.

- `OK` — score from full-quality evidence.
- `DEGRADED` — score computed from less than half of the documented factor weight.
- `UNAVAILABLE` — no analyzable data (score is `null`, signal `unavailable`).

`signal_from_score()` mapping is shared by all agents. Outputs persist to `agent_outputs` and are
listed via `GET /api/agents/outputs?agent_id=…&symbol=…&limit=…` (newest first).

## 18. Provenance / evidence philosophy

The UI communicates the product, not the source code: "Price history used for market momentum",
"17 relevant financial articles analysed", "Peer price history used for industry comparison".
Every analytical output links evidence entries (data type, reference, source, timestamp, note) and
lists its limitations. Developer internals — DB paths, endpoint names, repo files — stay out of the
demo UI.

## 19. Missing-data handling

Missing data reduces evidence and confidence; it never invents values. Firm needs ≥ 2 price points
for momentum; single-period filings leave revenue growth unavailable; single-member sectors produce
no peer factors; absent FinBERT or `NEWS_API_KEY` yields explicit `UNAVAILABLE`. `DEGRADED` vs `OK`
is decided by documented factor-weight coverage (< 50% → `DEGRADED`).

## 20. Industry automatic data preparation

Before every Industry Analyst run, `AgentService` calls
`MarketService.ensure_history(symbols, min_bars, max_age_days=7)` for the company and its sector
peers: sufficient **fresh** cached history is reused as-is (provider not called); only missing/stale
symbols go through the normal refresh pipeline; provider failures are isolated per symbol and never
raised, so analysis still runs on valid cached data with honest limitations. A transparent
`data_preparation` summary (cached/refreshed/failed per symbol) is recorded in the output provenance.
Agents stay repository-only — no provider coupling.

## 21. Database / storage

Single local DuckDB file (default `data/processed/fincortext.duckdb`, overridable via
`FINCORTEXT_DB_PATH`): `market_prices, universe_metadata, financial_observations,
filing_documents, news_articles, sentiment_results, agent_outputs, data_provenance`.
Thread-safe wrapper, hash-dedup on filings/news, startup repair keeps market rows keyed by canonical
internal symbol. Raw artifacts archived under `data/raw/`; sample fixtures under `data/sample/`.

## 22. API structure

| Method & path | Purpose |
|---|---|
| `GET /health` | Service status + safe config summary (no secrets) |
| `GET /api/universe`, `GET /api/universe/{symbol}` | Versioned universe entries |
| `POST /api/market/refresh`, `POST /api/market/refresh/{symbol}` | Refresh OHLCV (synchronous) |
| `GET /api/market/prices/{symbol}?start=&end=` | Stored series + status |
| `GET /api/market/status` | Per-symbol storage coverage |
| `POST /api/filings/import` | Multipart official-file ingestion |
| `GET /api/filings?symbol=` | Ingested documents |
| `POST /api/fundamentals/refresh`, `POST /api/fundamentals/refresh/{symbol}` | Refresh provider fundamentals (supplements filings; per-symbol failure isolation) |
| `GET /api/fundamentals/{symbol}` | Metric coverage with per-metric source labels |
| `GET /api/news/status` | Provider configuration status |
| `POST /api/news/refresh/{symbol}?days=&page_size=` | Fetch live news |
| `GET /api/news/{symbol}?limit=` | Stored articles |
| `POST /api/agents/{agent}/{symbol}/run` | Run firm/industry/sentiment (`firm` aliases accepted; macro/portfolio → explicit 404) |
| `GET /api/agents/outputs?agent_id=&symbol=&limit=` | Output history, newest first |

## 23. Frontend routes

Demo sidebar (the product): `/` Dashboard (market overview: price, chart, sector peers,
stored intelligence, news, derived takeaway) · `/company` Company Analysis (price statistics,
data inventory, analyst run history, peers) · `/intelligence/firm` · `/intelligence/industry` ·
`/intelligence/sentiment` · `/intelligence/summary` · `/roadmap` (future-module skeletons,
all labeled Under Development). Internal tooling stays mounted but unlinked:
`/data/*` (sources, pipeline, market, filings, quality); future placeholders: `/intelligence/macro`,
`/portfolio*`, `/research/*`. No index, market-cap or blended-score figures exist anywhere —
the backend provides none, so the UI invents none.

## 24. Configuration / environment variables

| Variable | Default | Purpose |
|---|---|---|
| `NEWS_API_KEY` | (empty) | NewsAPI key; absent → news `UNAVAILABLE`, everything else works |
| `FINCORTEXT_DB_PATH` | `data/processed/fincortext.duckdb` | DuckDB location |
| `FINCORTEXT_HOST` / `FINCORTEXT_PORT` | `127.0.0.1` / `8000` | Backend bind |
| `FINCORTEXT_CORS_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173` | Dev CORS |
| `FINCORTEXT_LOG_LEVEL` | `INFO` | Logging (secrets redacted) |
| `FINCORTEXT_MARKET_HISTORY_DAYS` | `730` | Lookback for market refresh |
| `FINCORTEXT_SENTIMENT_MODEL` | `ProsusAI/finbert` | HF model id |
| `FINCORTEXT_SENTIMENT_CACHE_DIR` | `data/cache/sentiment-model` | Local model cache |
| `FINCORTEXT_ALLOW_SAMPLE_DATA` | `true` | Sample fixtures only on explicit request |

Put them in a root `.env` file (loaded automatically; real environment variables win) — never commit
secrets. There is no `.env.example` checked in; the table above is the reference.

## 25. Installation

```bash
# Backend
pip install -r backend/requirements.txt   # Python 3.11+

# Frontend
cd frontend && npm install                 # Node.js 18+
```

## 26. Running the backend

```bash
cd backend
python -m uvicorn app.main:app --reload --port 8000
```

- Health: http://127.0.0.1:8000/health
- API docs: http://127.0.0.1:8000/docs

## 27. Running the frontend

```bash
cd frontend
npm run dev
```

Open http://localhost:5173 (API calls are proxied to the backend).

## 28. Testing

```bash
cd backend && python -m pytest            # unit + integration; add -m network for live-provider tests
cd frontend && npm test                   # Vitest component tests
cd frontend && npm run build              # production build (tsc + vite)
```

Markers: `unit` (fast, isolated), `integration` (cross-module), `system` (end-to-end style),
`network` (internet required, deselected by default).

## 29. Current test status

- Backend: **172 passed** (`python -m pytest`).
- Frontend: **41 passed** (`npm test`) — sidebar navigation, expansion/roadmap skeleton,
  company search/switching, dashboard honesty (no invented indices/scores), takeaway
  derivation, company analysis page (incl. fundamentals coverage), context isolation,
  no-stale/mid-flight run guards, side-by-side-no-blend summary, stored-news status,
  analysis-vs-data dates, coverage indicator, price-stat unit tests, symbol persistence,
  no-refetch on remount, badge/card rendering.
- Frontend production build: clean.

## 30. Current limitations

- Live yfinance/NewsAPI untested in CI (network-dependent; adapters covered by fakes/mocked HTTP).
- `POST /api/market/refresh` is synchronous — a full-universe refresh takes ~10–30s live.
- PDF filing parsing is a basic extraction fallback, not a reliable parser for arbitrary annual reports.
- Firm momentum needs ≥ 2 price points; single-period filings leave revenue growth unavailable.
- Industry peer set is limited to the 10-symbol universe; single-member sectors yield no peer factors.
- FinBERT downloads on first sentiment run (~440 MB); until then sentiment reports `UNAVAILABLE`.
- Provider fundamentals supplement official filings (labeled `source_type=yfinance`,
  never official): annual statements carry real fiscal periods; snapshot P/E + ROE carry
  no statement period (`available_at` = ingestion time) and must not be used for historical
  evaluation. No website scraping — Yahoo Finance API via yfinance; no Screener.in.
- Sentiment relevance screening is deterministic and lexical (identity +
  financial context, documented trade-offs for short brand tokens); NewsAPI free tier
  caps history (~30 days).
- Universe sector/industry metadata is configuration, not verified against a licensed classifier.
- Single-user local research tool: no auth, no multi-tenancy.

## 31. Demo workflow

1. Open the Dashboard — search a company in the top bar (e.g. **TCS**, **RELIANCE**, **INFY**).
2. Review the identity header (price, day change, day high/low, volume), the stored-history
   chart with range selector, sector peers with real quotes, stored intelligence and news.
3. Press **▶ Analyze Company** → Company Analysis (price statistics, data inventory
   incl. fundamentals coverage with source labels, peers).
4. Firm Analyst → run (fundamentals + momentum; missing inputs stay honestly unavailable).
5. Sentiment Analyst → fetch news (if configured), then run.
6. Intelligence Summary → run all three; views sit side by side with evidence and limitations.
7. Navigate freely — company choice and results persist; nothing re-runs unless you ask.

## 32. Future roadmap

`/roadmap` in the app lists the planned modules as labeled skeletons (no functionality):
Macro Analyst → Portfolio Agent (consumes `AgentOutput`s, confidence-weighted) → risk/constraint
engine → optimization → backtesting on the preserved point-in-time metadata → performance evaluation
→ scenario/stress testing → licensed data providers → auth/deployment. The architecture seams
(provider interfaces, `AgentOutput` contract, provenance log) are already in place for these.

---

*Continuing development? Read [PROGRESS.md](PROGRESS.md), then [ARCHITECTURE.md](ARCHITECTURE.md)
and [docs/agent_contracts.md](docs/agent_contracts.md).*
