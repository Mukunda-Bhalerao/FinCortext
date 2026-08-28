# FinCortext — Implementation Progress

This document is the **continuation contract** for any coding agent working on
FinCortext. It is updated after every milestone.

---

## COMPLETED

### Milestone 1 — Repository Foundation ✅
- Monorepo scaffold: `backend/`, `frontend/`, `data/`, `docs/`, `scripts/`
- Backend: FastAPI app factory, config from env/`.env`, structured logging with
  secret redaction, domain exception hierarchy, `GET /health`
- Frontend: React 18 + TypeScript + Vite app shell, dark financial theme,
  routing for all sections, explicit "Coming soon" placeholders
- Root docs: `README.md`, `ARCHITECTURE.md`, `.env.example`, `.gitignore`

### Milestone 2 — Domain Contracts + Storage ✅
- Canonical domain models (`app/domain/models/`): `MarketPrice`,
  `FinancialObservation` (point-in-time `available_at` fallback chain),
  `FilingDocument`, `NewsArticle`, `SentimentResult`, `UniverseEntry`,
  `Provenance`, `DataStatus`/`DataSourceType` enums
- **Standardized `AgentOutput` contract** (`agent_output.py`): score/signal/
  confidence/factors/rationale/evidence/limitations/provenance/status +
  documented `signal_from_score()` mapping shared by all agents
- Provider interfaces (`app/domain/contracts/providers.py`): `MarketDataProvider`,
  `FundamentalDataProvider` (fallback-only), `NewsProvider`
- Versioned universe config (`app/data/universe/universe_config.py`): 10 NSE
  large-caps with symbol/name/exchange/ticker/sector/industry; peer lookups
- DuckDB storage (`app/data/storage/duckdb_storage.py`): thread-safe wrapper,
  8-table schema
- Repositories: market, financial (point-in-time queries, hash-dedup), news,
  agent_output, universe (config mirror), provenance (event log)
- Docs: `docs/data_model.md`, `docs/agent_contracts.md`

### Milestone 3 — Market Data Pipeline ✅ (details in git history)
- `YFinanceMarketProvider` (`app/data/providers/market/yfinance_provider.py`):
  implements `MarketDataProvider`, NSE `.NS` ticker mapping from universe
  config, MultiIndex frame normalization, ProviderError on all failures
- Market validation (`app/data/validation/market_validation.py`): positive
  prices, high>=low, open/close within range, duplicate detection; rejections
  reported with reasons (never silently dropped)
- `MarketService` (`app/services/market_service.py`): refresh symbol/universe
  (per-symbol failure isolation), price series with LIVE/CACHED/UNAVAILABLE
  status, provenance recording
- Service container (`app/services/container.py`): composition root
- API routes: `GET /api/universe`, `GET /api/universe/{symbol}`,
  `POST /api/market/refresh[/{symbol}]`, `GET /api/market/prices/{symbol}`,
  `GET /api/market/status`
- Tests: validation unit tests, yfinance normalization (fake MultiIndex frame),
  error wrapping, integration test fake-provider→validation→DuckDB→API

### Milestone 4 — Official Filing Ingestion ✅
- Metric mapping config (`app/data/ingestion/filings/metric_mapping.py`):
  label→canonical metric tables (CSV labels + XBRL element names), documented
- Parsers (`app/data/ingestion/filings/parsers.py`):
  - CSV: flexible schema (metric/label/item + value/amount), unit/currency/
    period/statement/consolidation/fiscal-year/filing-date columns, unmapped
    labels + unparseable values reported as warnings
  - XBRL/XML: stdlib ElementTree, contextRef period resolution (duration +
    instant), unitRef resolution, taxonomy-element mapping
  - PDF: LIMITED pypdf text-extraction fallback with explicit quality
    warnings (never claims reliable parsing of arbitrary reports)
- `FilingService`: SHA-256 content-hash dedup, raw file archiving under
  `data/raw/filings/`, point-in-time metadata attachment, provenance events
- API: `POST /api/filings/import` (multipart upload), `GET /api/filings`
- Sample fixtures: `data/sample/sample_filing.csv`, `data/sample/sample_filing.xbrl`
- Docs: `docs/data_sources.md`
- Tests: parser unit tests (fixtures, number/date parsing, error paths,
  minimal hand-built PDF), ingestion integration tests (CSV/XBRL end-to-end,
  duplicate detection, unknown symbol, unsupported format)

### Milestone 5 — Firm Analyst ✅
- Base agent interface (`app/agents/base/base_agent.py`): analyze/run/persist
- Documented methodology (`app/agents/firm/methodology.py`): 6 factors with
  explicit weights (profitability 0.25, revenue_growth 0.20, financial_health
  0.20, return_on_equity 0.15, valuation 0.10, market_momentum 0.10), linear
  score bounds, weight redistribution for missing factors, deterministic
  confidence = coverage × quality tier
- `FirmAgent` (`app/agents/firm/firm_agent.py`): consumes FinancialRepository
  (ingested filings = primary truth) + MarketRepository (momentum); never
  fabricates missing metrics; emits full AgentOutput with factors, rationale,
  evidence, limitations, provenance; UNAVAILABLE status when no data
- `AgentService` + routes: `POST /api/agents/{agent_id}/{symbol}/run`
  (aliases: firm/industry/sentiment), `GET /api/agents/outputs`;
  macro/portfolio rejected with explicit "not implemented" 404
- Tests: methodology math (linear score, clamping, redistribution, confidence
  tiers, determinism), FirmAgent behavior (full data, missing data, no data,
  growth periods, negative growth), integration filing→DuckDB→agent→API

### Milestone 6 — Industry Analyst ✅
- Methodology (`app/agents/industry/methodology.py`): 4 documented factors —
  peer_momentum 0.30, relative_strength 0.30, peer_fundamentals 0.25,
  sector_volatility 0.15; median-based peer stats; company excluded from peer
  medians; weight redistribution for missing factors; deterministic
  confidence = coverage × quality tier
- Volatility convention documented and deterministic: simple daily returns,
  population std-dev (ddof=0), × √252; identical returns short-circuit to
  exactly 0.0 (fixes floating-point residual bug); `math.fsum` summation
- `IndustryAgent` (`app/agents/industry/industry_agent.py`): peer grouping
  from versioned universe config (sector, industry fallback), 90-day momentum
  window, peer medians via MarketRepository + FinancialRepository, full
  AgentOutput with factors/rationale/evidence/limitations/provenance,
  UNAVAILABLE when no data
- `AgentService.run_agent(..., persist=)` passthrough added (deterministic
  re-runs without double-persisting)
- Methodology doc: `docs/industry_methodology.md`
- Tests: methodology math (weights, median, volatility conventions, linear
  score, combination determinism), agent behavior (relative strength seeded
  series, no-data UNAVAILABLE, API endpoint + output history)

### Milestone 7 — News + Sentiment ✅
- `NewsAPINewsProvider` (`app/data/providers/news/newsapi_provider.py`):
  implements the existing `NewsProvider` contract; key ONLY from
  `NEWS_API_KEY` env (never hardcoded); missing key → ProviderUnavailableError;
  401/403 → unavailable, 429 → rate-limit error, network/API failures →
  ProviderError; never fabricates articles
- Article normalization: canonical `NewsArticle` with stable `article_id`
  (SHA-256 of URL; title+timestamp fallback), `content_hash` audit hash,
  source metadata, publication/collection timestamps, language
- `NewsService` (`app/services/news_service.py`): entity association,
  dedup-on-store, provenance events, explicit LIVE/CACHED/UNAVAILABLE/ERROR
  statuses; missing key degrades gracefully (backend + unrelated modules keep
  working); provider crashes never propagate
- Sentiment model (`app/agents/sentiment/model.py`): lazy-loading local
  FinBERT (ProsusAI/finbert default, configurable); any load/inference failure
  → ModelUnavailableError → explicit UNAVAILABLE output; backend never crashes
  on model problems; no paid API
- Methodology (`app/agents/sentiment/methodology.py`): documented polarity
  P(pos)−P(neg), recency weighting with 7-day half-life anchored to the
  latest article timestamp (data-anchored determinism), composite score
  mapping to 0–100, confidence = 0.35·coverage + 0.25·model_confidence +
  0.25·consistency + 0.15·recency
- `SentimentAgent` (`app/agents/sentiment/sentiment_agent.py`): relevance
  filter (name/symbol), per-article SentimentResult persistence, full
  AgentOutput (score/signal/confidence/factors/evidence/rationale/
  limitations/provenance), OK/DEGRADED/UNAVAILABLE status semantics
- API: `GET /api/news/status`, `POST /api/news/refresh/{symbol}`,
  `GET /api/news/{symbol}`; sentiment agent enabled via
  `POST /api/agents/sentiment/{symbol}/run`
- Docs: `docs/sentiment_methodology.md`
- Tests: NewsAPI normalization/dedup identity/error paths (mocked HTTP, no
  network), NewsService degradation/dedup/provenance, sentiment aggregation
  math (recency, determinism, confidence components), SentimentAgent behavior
  (fake model; unavailable/degraded/OK), integration fixture-provider→
  storage→sentiment→API + missing-key graceful endpoints

## CURRENT STATE

- Backend: 114 tests passing. Market pipeline, filing ingestion, Firm
  Analyst, Industry Analyst, and News+Sentiment all working offline
  (fixtures/fakes; live providers network-optional).
- Frontend unchanged (builds clean).
- All three implemented agents (firm/industry/sentiment) emit the
  standardized AgentOutput via `POST /api/agents/{agent}/{symbol}/run`.

## TEST STATUS

- `cd backend && python -m pytest` — **114 passed**
  (M7 focused run: 41 passed; M6 focused run: 8 passed)
- Frontend `npm run build` — passing

## KNOWN LIMITATIONS

- Live yfinance/NewsAPI untested in CI (network-dependent; adapters covered
  by fakes/mocked HTTP).
- `POST /api/market/refresh` is synchronous — 10 symbols take ~10-30s live.
- PDF parsing is explicitly a limited fallback (documented in results).
- Firm Agent needs ≥2 price points for momentum; single-period filings leave
  revenue_growth unavailable (by design — no fabrication).
- Industry Analyst peer set limited to the 10-symbol universe; single-member
  sectors produce no peer factors (docs/industry_methodology.md).
- FinBERT downloads on first sentiment run (~440MB) into
  `data/cache/sentiment-model`; until then sentiment reports UNAVAILABLE.
- Sentiment relevance matching is lexical (name/symbol); NewsAPI free tier
  caps history (~30 days).

## NEXT RECOMMENDED STEP

**Milestone 8 — Frontend Integration**: wire the existing React shell to the
full API (universe, market, filings, news, all three agents), company-centric
demonstration flow, explicit LIVE/CACHED/IMPORTED/SAMPLE/UNAVAILABLE/ERROR
data-status badges, filing upload UI, combined intelligence summary, and
honest "Coming soon" placeholders for Macro/Portfolio/Research.
