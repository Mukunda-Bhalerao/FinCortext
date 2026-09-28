# FinCortext

**Investment intelligence research platform — fundamentals, industry position, and news sentiment, with the evidence attached.**

FinCortext reads a listed company from four independent perspectives — a Firm Analyst (fundamentals + market
behavior), an Industry Analyst (peer and sector-relative position), a Sentiment Analyst (financial-news
tone), and a market-wide Macro Analyst (environment, never a stock call) — and combines them in a
Portfolio Synthesis layer that explains how the views fit together without blending them into one score.
Every score carries its factors, rationale, evidence references, limitations, and provenance. Missing data
is reported honestly; nothing is fabricated to fill a gap.

---

## 1. What FinCortext is

A research-oriented financial intelligence platform for Indian NSE large-caps. It ingests market prices,
official filing data, and financial news through replaceable provider adapters, normalizes them into
canonical domain data stored in DuckDB, and runs deterministic analyst agents whose standardized outputs
are consumed by the Portfolio Synthesis layer.

The current demo covers the **Data → Intelligence → Decision-support** arc
(Data → Intelligence → Decision → Optimization → Evaluation). The Portfolio
Synthesis page is the decision-support layer (perspectives compared, never
blended — no overall score). Optimization and evaluation layers are explicitly
future work.

## 2. Problem being addressed

Retail-grade research tooling typically gives you either raw prices with no interpretation, or opaque
scores with no evidence. FinCortext targets the middle: every analytical claim must be traceable to the
stored data it was computed from, and every gap in the data must be visible as a gap — not silently
papered over.

## 3. Project objective

Build a working, testable foundation for explainable investment intelligence:

1. Canonical data layer with provenance and point-in-time correctness.
2. Deterministic analyst agents with documented methodologies.
3. A standardized output contract (`AgentOutput`, plus `MacroOutput` / `PortfolioView`) feeding the
   Portfolio Synthesis decision-support layer.
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
- **Macro Analyst** — market-wide environment view (growth, inflation, rates, liquidity, policy,
  global, events) with deterministic POSITIVE/NEUTRAL/NEGATIVE signals plus a 0–100 environment
  score (linear rescaling of the available-factor vote, always agreeing with the signal), own
  `MacroOutput` contract, and per-indicator provenance. Environment only — never a stock
  recommendation, never blended.
- **News + Sentiment pipeline** — NewsAPI provider, local FinBERT model, deterministic time-aware aggregation.
- **Portfolio Synthesis (Central Orchestrator)** — per-company decision-support view combining the
  four analyst perspectives without blending: four perspective cards (Macro headed "Market
  Environment"), agreement/conflict thesis with strongest/weakest views, conditional Base/Bull/Bear
  scenarios, collapsible evidence/risks grouped by analyst. No overall score; macro never a stock call.
- React + TypeScript research frontend (Dashboard, Company Analysis, four analysts, Combined Summary,
  Portfolio Synthesis) with explicit
  data-status labels (`LIVE` / `CACHED` / `IMPORTED_OFFICIAL` / `SAMPLE` / `UNAVAILABLE` / `ERROR`).
- Session-wide frontend research state: company selection and results survive navigation without
  re-running analyses.

**PARTIALLY IMPLEMENTED:**

- PDF filing parsing (basic text-extraction fallback only — documented as unreliable for arbitrary reports).
- Sample-data support (served only on explicit request, never silently substituted).

**FUTURE (explicit placeholders, not implemented):**

- Risk & constraint engine, portfolio optimization (weights), backtesting,
  performance evaluation, scenario/stress testing, explainability module beyond
  per-agent rationale/evidence and the synthesis thesis, authentication,
  deployment infrastructure, licensed data providers.

## 5. Core design philosophy

1. **Source-agnostic agents.** Analysts consume canonical domain data through repositories/services —
   never external providers or websites.
2. **Replaceable providers.** Every external source sits behind a narrow interface
   (`MarketDataProvider`, `FundamentalDataProvider`, `NewsProvider`, `MacroDataProvider`).
3. **Deterministic intelligence.** Scores come from documented, testable formulas — no randomness, no
   invented conclusions.
4. **Provenance and point-in-time correctness.** Every observation records where it came from and when
   it became available (`period_end` vs `available_at`), so future backtests stay honest.
5. **Honest degradation.** Missing keys, provider outages, or unavailable models produce explicit
   statuses — never silently substituted data.

## 6. System architecture

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full description. In brief:

```
Data Sources (yfinance | NewsAPI | official filings | curated macro | fixtures)
        ↓  provider adapters (replaceable interfaces)
Data Pipeline (ingestion → validation → normalization → storage)
        ↓
DuckDB canonical storage (+ provenance, point-in-time metadata)
        ↓  repositories / services (source-agnostic)
Agent Layer (Firm Analyst | Industry Analyst | Macro Analyst | Sentiment Analyst)
        ↓  AgentOutput contract (+ dedicated MacroOutput for the market-wide view)
Portfolio Synthesis (Central Orchestrator — perspectives compared, never blended; no overall score)
        ↓  PortfolioView contract
FastAPI services/routes  →  React frontend (Dashboard · analysts · summary · synthesis)
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
| Market prices | `UpstoxMarketProvider` (Upstox, primary when `LIVE_MARKET_PROVIDER=upstox`) + `YFinanceMarketProvider` (fallback) | Upstox instrument search / full quotes V3 / historical candles V3; NSE-equity filter; `instrument_key` canonical. Canonical storage key is always the internal symbol (`TCS`), never the provider ticker (`TCS.NS`). yfinance fallback bars are honestly marked `yfinance` and can never overwrite newer Upstox data. |
| News | `NewsAPINewsProvider` (NewsAPI) | Key **only** from `NEWS_API_KEY`; missing key → graceful `UNAVAILABLE`, never a crash. 401/403 → unavailable, 429 → rate-limit error. Company-name query variants tried during preparation. |
| Fundamentals | Ingested official filings (primary truth) + provider annual statements (fallback) | `YFinanceFundamentalsProvider` implements the `FundamentalDataProvider` seam: annual income/balance rows with real fiscal periods plus snapshot P/E + ROE. Stored as `source_type=yfinance`, never as official filings. |
| Web research | `GeminiResearchProvider` (official `google-genai` SDK, Search grounding) | Research/enrichment **only**: company sector/industry classification, peer candidates, news digests. Never market data, never scores. Key **only** from `GEMINI_API_KEY` (SDK client arg only, never logged); missing key → `UNAVAILABLE`. Failures carry distinct sanitized diagnostics (invalid key / retired model naming `GEMINI_MODEL` / rate limit / endpoint / timeout). Evidence stored in `research_reports`, never as articles or prices. |
| Future | Licensed feeds, RSS/GDELT, industry reports | Seams reserved at the provider boundary. |

## 11. Market data pipeline

`MarketService.refresh_symbol` → provider fetch → validation (positive prices, high ≥ low,
open/close within range, duplicates) → normalization → DuckDB → provenance event → API
(`POST /api/market/refresh[/{symbol}]`, `GET /api/market/prices/{symbol}` with
`LIVE`/`CACHED`/`UNAVAILABLE` status, `GET /api/market/status` for universe-wide coverage).
Per-symbol failure isolation: one bad symbol never blocks the rest of the universe.

## 12. News pipeline

Provider fetch (Google News RSS by default, NewsAPI optional — both merged with
dedup when configured) → canonical `NewsArticle` (stable `article_id` = SHA-256 of URL,
`content_hash` audit hash, source metadata, publication/collection timestamps) →
`NewsService` entity association + dedup-on-store + provenance → DuckDB → API
(`GET /api/news/status`, `POST /api/news/refresh/{symbol}`, `GET /api/news/{symbol}`).
Google News RSS is free and keyless (feed XML only, no article scraping; polite
fetching with retries and a 6h cache); NewsAPI stays as an optional secondary
merge source. Missing keys degrade gracefully; the backend and all unrelated
modules keep working.

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
× √252). Peer grouping comes from the versioned universe config, extended to any searched
stock: official NSE Nifty 500 industry list (committed CSV) classifies dynamic equities,
and peers are drawn from configured entries, curated candidates, and same-industry CSV
symbols — every peer validated live with real price history before it counts.
Agent runs resolve renamed/demerged symbols canonically (ZOMATO→ETERNAL,
TATAMOTORS→TMCV); unknown symbols stay honest 404s.
Methodology: [docs/industry_methodology.md](docs/industry_methodology.md).

## 15. Sentiment Analyst

Deterministic financial-relevance screen (`relevance.py`: company identity AND
financial/business context required, brand-sport/tragedy/retail-promo topics
excluded, former-affiliation bio-lines disqualified; identity patterns are
auto-generated from any company name — curated aliases keep priority, single
common-noun words stay case-sensitive; stored/relevant/rejected
counts with per-reason breakdown in every output) → local FinBERT
(ProsusAI/finbert default, configurable; lazy-loaded, ~440 MB first download)
→ polarity P(pos) − P(neg) → recency-weighted aggregation with 7-day
half-life anchored to the latest article timestamp → composite 0–100 score with confidence =
0.35·coverage + 0.25·model_confidence + 0.25·consistency + 0.15·recency. Model load/inference
failures → explicit `UNAVAILABLE`, never a crash. Methodology:
[docs/sentiment_methodology.md](docs/sentiment_methodology.md).

## 16. Macro Analyst (market-wide)

Seven deterministic areas — growth, inflation, interest rates, liquidity/credit, fiscal &
monetary policy, global markets, macro events — each with value, direction, POSITIVE/NEUTRAL/
NEGATIVE environment signal, confidence, status, as-of date, evidence and limitations. Overall
signal = majority vote; confidence = coverage × recency × consistency. A 0–100 Macro Environment
Score linearly rescales the same available-factor vote (`50 + 50·net/n`, unavailable areas
excluded), so it always agrees with the signal — and like the signal it describes the environment
only. Data: curated RBI/MoSPI
history (versioned CSVs with per-row provenance) + market gauges via yfinance. Liquidity has no
reliable series and reports UNAVAILABLE rather than a proxy. Output is the dedicated
`MacroOutput` contract (`entity_id=MACRO_INDIA`, with environment score) — never a stock signal.
Methodology: [docs/macro_methodology.md](docs/macro_methodology.md).

## 17. Combined Summary

Runs the four analysts and shows their perspectives side by side — three company scores plus
the market-wide macro environment score. Each analyst is independent — company analysts share only
the `AgentOutput` contract, macro uses its own. **No blending into a single
score, no recommendations, no weights.** The explained synthesis lives on the
Portfolio Synthesis page (§18).

## 18. Portfolio Synthesis (Central Orchestrator)

Per-company decision-support layer (`POST /api/agents/portfolio/{symbol}/run`, reads via
`GET /api/portfolio/latest|history?symbol=`; frontend `/portfolio`): four distinct perspective
cards (Firm, Industry, Sentiment, Macro — each with score, signal, confidence, status; Macro
headed "Market Environment" with the bare signal and a market-wide warning), an investment-thesis
panel (positive/neutral/negative counts, strongest-supported and most-uncertain views,
disagreements shown, evidence-based wording), conditional Base/Bull/Bear scenario cards
(analyst tags derived from the backend wording — conditions, never predictions, no probabilities
or price targets), and collapsible Supporting evidence / Key risks (grouped by analyst) /
Limitations sections (rendered only for genuine warnings). Deterministic synthesis over stored
outputs — **no overall score, no averaging, macro never a stock recommendation.**

## 19. AgentOutput contract

Every company analyst emits the same shape (see [docs/agent_contracts.md](docs/agent_contracts.md)):

`agent_id, entity_id, score (0–100 | null), signal (strong_buy … strong_sell | unavailable),
confidence, factors[], rationale, evidence[], data_limitations[], generated_at, data_version,
provenance, status`.

- `OK` — score from full-quality evidence.
- `DEGRADED` — score computed from less than half of the documented factor weight.
- `UNAVAILABLE` — no analyzable data (score is `null`, signal `unavailable`).

`signal_from_score()` mapping is shared by all company analysts. Outputs persist to `agent_outputs` and are
listed via `GET /api/agents/outputs?agent_id=…&symbol=…&limit=…` (newest first). The Macro Analyst
uses the separate `MacroOutput` contract (`entity_id=MACRO_INDIA`, POSITIVE/NEUTRAL/NEGATIVE,
with 0–100 environment score), persisted to `macro_outputs`. The Portfolio Synthesis emits the
`PortfolioView` contract (perspectives, agreement, thesis, scenarios, evidence, risks,
coverage/confidence — no overall score), persisted to `portfolio_outputs`.

## 20. Provenance / evidence philosophy

The UI communicates the product, not the source code: "Price history used for market momentum",
"17 relevant financial articles analysed", "Peer price history used for industry comparison".
Every analytical output links evidence entries (data type, reference, source, timestamp, note) and
lists its limitations. Developer internals — DB paths, endpoint names, repo files — stay out of the
demo UI.

## 21. Missing-data handling

Missing data reduces evidence and confidence; it never invents values. Firm needs ≥ 2 price points
for momentum; single-period filings leave revenue growth unavailable; single-member sectors produce
no peer factors; absent FinBERT or `NEWS_API_KEY` yields explicit `UNAVAILABLE`. `DEGRADED` vs `OK`
is decided by documented factor-weight coverage (< 50% → `DEGRADED`).

## 22. Industry automatic data preparation

Before every Industry Analyst run, `AgentService` calls
`MarketService.ensure_history(symbols, min_bars, max_age_days=7)` for the company and its sector
peers: sufficient **fresh** cached history is reused as-is (provider not called); only missing/stale
symbols go through the normal refresh pipeline; provider failures are isolated per symbol and never
raised, so analysis still runs on valid cached data with honest limitations. A transparent
`data_preparation` summary (cached/refreshed/failed per symbol) is recorded in the output provenance.
Agents stay repository-only — no provider coupling.

## 23. Database / storage

Single local DuckDB file (default `data/processed/fincortext.duckdb`, overridable via
`FINCORTEXT_DB_PATH`): `market_prices, universe_metadata, financial_observations,
filing_documents, news_articles, sentiment_results, agent_outputs, data_provenance,
macro_observations, macro_outputs, portfolio_outputs`.
Thread-safe wrapper, hash-dedup on filings/news, startup repair keeps market rows keyed by canonical
internal symbol. Raw artifacts archived under `data/raw/`; sample fixtures under `data/sample/`.

## 24. API structure

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
| `POST /api/agents/{agent}/{symbol}/run` | Run firm/industry/sentiment/macro (`firm` aliases accepted) |
| `POST /api/agents/portfolio/{symbol}/run` | Full synthesis: runs all four analysts for the company, then synthesizes (no overall score) |
| `GET /api/agents/outputs?agent_id=&symbol=&limit=` | Output history, newest first |
| `POST /api/macro/data/refresh`, `POST /api/macro/data/refresh/{indicator}` | Refresh macro indicators (per-indicator failure isolation) |
| `GET /api/macro/indicators`, `GET /api/macro/series/{indicator}` | Indicator coverage / stored series |
| `GET /api/macro/latest`, `GET /api/macro/history?limit=` | Latest / historical macro environment views |
| `GET /api/portfolio/latest?symbol=`, `GET /api/portfolio/history?symbol=&limit=` | Latest / historical synthesis views per company |

## 25. Frontend routes

Demo sidebar (the product): `/` Dashboard (market overview: price, chart, sector peers,
stored intelligence, macro strip, news, derived takeaway) · `/company` Company Analysis (price statistics,
data inventory, analyst run history, peers) · `/intelligence/firm` · `/intelligence/industry` ·
`/intelligence/macro` (market-wide environment view with score) · `/intelligence/sentiment` ·
`/intelligence/summary` (four perspectives side by side, never blended) · `/portfolio` Portfolio
Synthesis (perspective cards, thesis, conditional scenarios, collapsible evidence/risks) ·
`/roadmap` (future-module skeletons,
all labeled Under Development). Internal tooling stays mounted but unlinked:
`/data/*` (sources, pipeline, market, filings, quality);
future placeholders: `/portfolio/risk`, `/portfolio/optimization`, `/research/*`. No index, market-cap
or blended-score figures exist anywhere —
the backend provides none, so the UI invents none.

## 26. Configuration / environment variables

| Variable | Default | Purpose |
|---|---|---|
| `NEWS_PROVIDER` | `google_rss` | Primary news source: `google_rss` (free, keyless) or `newsapi`; the other configured source merges as secondary |
| `NEWS_API_KEY` | (empty) | NewsAPI key; absent → NewsAPI skipped (RSS still serves), everything else works |
| `LIVE_MARKET_PROVIDER` | `yfinance` | `upstox` selects Upstox as the primary market provider (yfinance stays as fallback) |
| `UPSTOX_ACCESS_TOKEN` | (empty) | Upstox key; absent → Upstox `UNAVAILABLE`, yfinance serves |
| `GEMINI_API_KEY` | (empty) | Gemini key; absent → web research `UNAVAILABLE`, everything else works |
| `GEMINI_MODEL` | `gemini-2.5-flash` | Gemini model id (must support generation for the key; `GET /api/research/verify` checks; switch without code changes) |
| `GEMINI_TIMEOUT_SECONDS` | `30` | Gemini request timeout |
| `GEMINI_WEB_SEARCH_ENABLED` | `true` | Gemini Search grounding (no website scraping) |
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

## 27. Installation

```bash
# Backend
pip install -r backend/requirements.txt   # Python 3.11+

# Frontend
cd frontend && npm install                 # Node.js 18+
```

## 28. Running the backend

```bash
cd backend
python -m uvicorn app.main:app --reload --port 8000
```

- Health: http://127.0.0.1:8000/health
- API docs: http://127.0.0.1:8000/docs

## 29. Running the frontend

```bash
cd frontend
npm run dev
```

Open http://localhost:5173 (API calls are proxied to the backend).

## 30. Testing

```bash
cd backend && python -m pytest            # unit + integration; add -m network for live-provider tests
cd frontend && npm test                   # Vitest component tests
cd frontend && npm run build              # production build (tsc + vite)
```

Markers: `unit` (fast, isolated), `integration` (cross-module), `system` (end-to-end style),
`network` (internet required, deselected by default).

## 31. Current test status

- Backend: **325 passed** (`python -m pytest`) — incl. Upstox provider, central
  preparation (incl. Gemini-enriched ADANIPOWER/BBL scenarios, mocked), 18
  SDK-mocked Gemini provider tests (incl. the BBL research task), startup-sync
  skip/retry tests, DuckDB concurrent-write regression tests, 19 Google News
  RSS tests, 12 industry-classifier tests, 10 auto-alias relevance tests, and
  an NHPC end-to-end prepare→industry+sentiment test (outside the original 10).
- Frontend: **61 passed** (`npm test`) — sidebar navigation (incl. Portfolio Synthesis),
  macro page/summary-strip with environment score, company search/switching, dashboard honesty
  (no invented indices/scores), takeaway derivation, company analysis page (incl. fundamentals
  coverage), context isolation, no-stale/mid-flight run guards, side-by-side-no-blend summary,
  stored-news status, analysis-vs-data dates, coverage indicator, price-stat unit tests, symbol
  persistence, no-refetch on remount, badge/card rendering, portfolio perspective cards/thesis/
  scenario/evidence-risk rendering, macro Market-Environment presentation, empty-vs-genuine
  Limitations, analyst/dashboard navigation.
- Frontend production build: clean.

## 32. Current limitations

- Live yfinance/NewsAPI untested in CI (network-dependent; adapters covered by fakes/mocked HTTP).
- `POST /api/market/refresh` is synchronous — a full-universe refresh takes ~10–30s live.
- PDF filing parsing is a basic extraction fallback, not a reliable parser for arbitrary annual reports.
- Firm momentum needs ≥ 2 price points; single-period filings leave revenue growth unavailable.
- Industry peers: configured universe first, then curated same-sector candidates, then
  Gemini-suggested peers — every candidate validated live via Upstox (exact-listing gate)
  with real market history before it counts. Companies whose sector cannot be established
  (research unavailable/unconfident) honestly report unavailable peer factors.
- Gemini web research needs a key with an available model id and quota; when the
  configured model is retired or quota is exhausted, research degrades to `UNAVAILABLE`
  with the reason stated (structured providers keep working). `GET /api/research/verify`
  performs a real minimal generation to confirm model+key health. Research never
  fabricates: low-confidence classifications are stored as evidence but not applied.
- Readiness honesty: backend `ready` requires market + fundamentals + metadata +
  peers + news; the UI says "Company data ready" only when market/fundamentals/
  company-info are READY, otherwise it names exactly what is ready vs unavailable.
- FinBERT downloads on first sentiment run (~440 MB); until then sentiment reports `UNAVAILABLE`.
- Provider fundamentals supplement official filings (labeled `source_type=yfinance`,
  never official): annual statements carry real fiscal periods; snapshot P/E + ROE carry
  no statement period (`available_at` = ingestion time) and must not be used for historical
  evaluation. No website scraping — Yahoo Finance API via yfinance; no Screener.in.
- Sentiment relevance screening is deterministic and lexical (identity +
  financial context, documented trade-offs for short brand tokens); NewsAPI free tier
  caps history (~30 days).
- Macro environment: curated RBI/MoSPI history is versioned but manually
  maintained (no live official feed reachable — DBnomics DNS fails from here,
  RBI scraping out of scope); liquidity/credit and fiscal feeds are honestly
  unavailable; market gauges need ~1 quarter of history before voting.
- Universe sector/industry metadata is configuration, not verified against a licensed classifier.
- Single-user local research tool: no auth, no multi-tenancy.

## 33. Demo workflow

1. Open the Dashboard — search a company in the top bar (e.g. **TCS**, **RELIANCE**, **INFY**).
2. Review the identity header (price, day change, day high/low, volume), the stored-history
   chart with range selector, sector peers with real quotes, stored intelligence, the macro
   environment strip, and news.
3. Press **▶ Analyze Company** → Company Analysis (price statistics, data inventory
   incl. fundamentals coverage with source labels, peers).
4. Firm Analyst → run (fundamentals + momentum; missing inputs stay honestly unavailable).
5. Macro Analyst → run (market-wide environment with score; identical for every company).
6. Sentiment Analyst → fetch news (if configured), then run.
7. Intelligence Summary → run all four; views sit side by side with evidence and limitations.
8. Portfolio Synthesis → run synthesis; perspective cards, agreement/conflict thesis, conditional
   scenarios, collapsible evidence/risks — no overall score.
9. Navigate freely — company choice and results persist; nothing re-runs unless you ask.

## 34. Future roadmap

`/roadmap` in the app lists the planned modules as labeled skeletons (no functionality):
risk/constraint engine → portfolio optimization (weights) → backtesting on the preserved
point-in-time metadata → performance evaluation → scenario/stress testing → licensed data providers
→ auth/deployment. The Portfolio Synthesis layer (§18) already consumes the analyst outputs through
the `PortfolioView` contract; the architecture seams (provider interfaces, output contracts,
provenance log) are already in place for the rest.

---

*Continuing development? Read [PROGRESS.md](PROGRESS.md), then [ARCHITECTURE.md](ARCHITECTURE.md)
and [docs/agent_contracts.md](docs/agent_contracts.md).*
