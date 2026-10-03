# Restructure Inventory (Phase 0 — pre-restructure state)

Branch: `restructure/upstox-unified-ux` (checkpoint tag `checkpoint/known-good-demo-pre-restructure` on `main`).
Date: 2026-10-03. This file records what worked, what was broken, and what is reusable
BEFORE any restructuring change was made.

## Live verification evidence (before any change)

- `scripts/verify_upstox_live.py` (added in Phase 0 as a verification tool):
  **4/4 symbols verified via Upstox only** (TCS, RELIANCE, INFY, HDFCBANK) —
  live full quotes (last/prev_close/OHLC/volume/year_high/year_low) AND
  historical daily candles (V3, 20 trading bars in 30 days) both served.
- Backend starts cleanly; `/health` 200 OK (`upstox_configured: true`,
  `gemini_configured: true`, `news_api_configured: true`, `allow_sample_data: false`).
- `GET /api/market/prices/TCS` → `CACHED`, 521 bars, latest 2026-09-25.
- `GET /api/market/quote/TCS` → LIVE Upstox quote (last 2075.0, year_high 3350.0,
  year_low 1976.8). Upstox is authoritative and covers both quotes and history.

## Baseline test results (pre-restructure)

- Backend: **unit + integration = 328 test functions**.
  - Unit: 1 FAILED (`test_company_preparation.py::test_agent_run_resolves_renamed_symbol`) —
    `AgentService.run_agent` calls `get_universe_entry(canonical)` at
    `app/services/agent_service.py:108` without registering the market-service-resolved
    rename (ZOMATO→ETERNAL), so the renamed symbol 404s. Genuine bug, not test rot.
  - Integration: **1 failed, 60 passed** in 83s
    (`test_portfolio_service_flow.py::test_run_portfolio_does_not_rerun_analysts`) —
    asserts 4 rows in `agent_outputs` for TCS, but Macro persists to the separate
    `macro_outputs` table (per the documented contract), so only 3 company rows exist.
    Test expectation contradicts the documented storage split.
  - Note: long pytest runs appear to hang when output is piped through PowerShell
    (`Select-Object`); redirecting to a file works. Use file-redirect for full runs.
- Frontend: **3 failed | 62 passed (65 tests)** — all 3 failures in
  `DashboardPage.test.tsx`, which is out of sync with the current "terminal" dashboard
  (expects the removed intel-label/macro-strip/news-list layout).

## What currently works

### Backend (`backend/app/`)
- FastAPI app factory, domain error handling, `/health`, secret-redacted logging.
- Providers: Upstox (search V2 / full quotes V3 / historical candles V3, NSE-EQ filter,
  token-only auth, honest `None` for missing fields), Google News RSS (keyless default),
  NewsAPI (optional secondary), Gemini research (grounded web research only), curated
  macro CSVs, yfinance market/fundamentals/macro adapters (fallback paths).
- MarketService: dynamic NSE-equity resolution (static universe never blocks; Upstox
  search + instrument registry + provider cache), live quote with stored-snapshot
  fallback (CACHED), OHLCV refresh → validation → DuckDB → provenance,
  `ensure_history` (cached-first, refresh only missing/stale), universe-wide refresh
  with per-symbol failure isolation.
- CompanyPreparationService: one SEARCH → PREPARE → STORE → AGENTS flow (resolve,
  metadata enrichment via Gemini when unknown, quote, history, fundamentals, news,
  peers with live Upstox validation, web_research area).
- FundamentalsService: yfinance annual statements + snapshot ratios labeled
  `source_type=yfinance`, scoped replace, coverage with per-metric source labels.
- Agents: Firm (6 factors), Industry (4 factors + automatic peer data prep),
  Sentiment (relevance screen + local FinBERT), Macro (7 factors, market-wide,
  MacroOutput contract), Portfolio synthesis (no blending, no overall score).
- Repositories: market/financial/news/filings/agent_output/universe/provenance/macro/
  portfolio/research/instrument over DuckDB.
- API routes: health, universe, market, filings, fundamentals, macro, portfolio,
  agents, news, research — thin handlers.

### Frontend (`frontend/src/`)
- React 18 + TS + Vite + react-router 6 + recharts (ResponsiveContainer only —
  candles are custom SVG in `CandleChart.tsx`).
- Shell: sidebar (8 nav items: Dashboard, Company Analysis, Firm/Industry/Macro/
  Sentiment Analysts, Intelligence Summary, Portfolio Synthesis) + topbar
  (CompanySelector + FreshnessPill warming caches), collapse persistence.
- FinCortextContext: session research state (symbol → `?symbol=` + localStorage,
  per-symbol caches with ref mirrors + in-flight dedup, run-result cache).
- Dashboard "terminal" page (identity header, range presets + candle chart,
  market context PeerTable, takeaway from stored outputs), Company Analysis
  (price stats + data inventory), 4 agent pages (+ shared AgentPage template for
  3 company analysts), Intelligence Summary, Portfolio Synthesis, Roadmap,
  5 unlinked `/data/*` internal pages, 5 placeholder routes.
- Honest states everywhere (skeletons, N/A, StatusBadge LIVE/CACHED/…), 62/65 tests pass.

## What is broken (pre-existing)

1. `AgentService.run_agent` renamed-symbol resolution 404s (backend unit test failure).
2. `test_run_portfolio_does_not_rerun_analysts` expects macro in `agent_outputs`
   (contradicts the documented macro_outputs storage split).
3. `DashboardPage.test.tsx` out of sync with the terminal dashboard (3 failures).
4. Dead dashboard tab anchors: `TABS` includes Intelligence/News ids that no longer
   exist in `DashboardPage.tsx`; news is fetched but never displayed on the Dashboard.
5. Dead CSS from the older dashboard (`.intel-*`, `.macro-strip`, `.kpi-*`, `.news-*`…).
6. `PreparationStatus` renders `null` everywhere (dead weight, still mounted in 4 pages).
7. `PlaceholderPage` copy says "V1 implements the Firm, Industry and Sentiment Analysts
   only" — Macro and Portfolio are implemented now.
8. Raw enums visible in UI: `MacroOutputCard` renders `direction` verbatim; both output
   cards render raw `status` values; `data_type`/methodology strings raw.
9. `MacroOutputCard` renders signal/status/confidence twice (badges + text line).
10. `/data/*` pages use their own local CompanySelector + direct `api` calls,
    bypassing the session context.
11. `IntelligenceSummaryPage` uses raw `<a href>` for the Portfolio link (full reload).
12. `api.market.refreshSymbol` POSTs literal `null` body (odd but functional).
13. `newestMarketTimestamp` exported but unused; `SystemArchitecture.jpeg` unreferenced.

## yfinance footprint (to be removed in Phase 1)

- `backend/requirements.txt` — `yfinance>=0.2.40`.
- `backend/app/data/providers/market/yfinance_provider.py` — full yfinance OHLCV adapter.
- `backend/app/data/providers/fundamentals/yfinance_fundamentals.py` — annual
  statements + snapshot P/E/ROE (FundamentalDataProvider seam implementation).
- `backend/app/data/providers/macro/yfinance_macro_provider.py` — macro gauges
  (USD/INR, Brent, US 10Y, India VIX daily closes) via yfinance.
- `backend/app/data/universe/industry_classifier.py` — `_default_yfinance_fetch` uses
  `yf.Ticker("{SYMBOL}.NS").info` as industry-classification fallback (step 3 after
  NSE CSV).
- `backend/app/services/container.py` — constructs all three yfinance providers;
  wires YFinanceMarketProvider as Upstox fallback.
- `backend/app/core/config.py` — `LIVE_MARKET_PROVIDER` defaults to `yfinance`.
- `backend/app/domain/models/base.py` — `DataSourceType.YFINANCE` enum member;
  `backend/app/domain/models/market.py` — `source_name` default `"yfinance"`.
- Fallback/labels elsewhere: `market_service.py` (yfinance-only branches), `market_repository.py`
  (source ranking Upstox > yfinance), `fundamentals_service.py` (labels), `macro_service.py`
  (labels), `upstox_provider.py` (fallback wiring), `universe_config.py` (yfinance-compatible
  ticker), `research_service.py` + `company_preparation_service.py` (doc references),
  `duckdb_storage.py` (comment), `core/logging.py` (yfinance logger level).
- Existing DB rows may carry `source_type=yfinance` provenance (historical data) —
  code must tolerate old rows even after the provider is removed.

## Macro gauges gap (Phase 1 consequence to address)

`YFinanceMacroProvider` fetches 4 market gauges (USD/INR, Brent, US 10Y, India VIX)
via yfinance. Removing yfinance removes these gauges unless Upstox covers them
(Upstox instrument search covers NSE instruments; USDINR may exist as NSE-IX series;
Brent/US10Y likely do NOT). Must be resolved with a verified replacement or an
explicit UNAVAILABLE — never silently dropped and never fabricated.

## Fundamentals gap (Phase 1 consequence to address)

`YFinanceFundamentalsProvider` is the only provider-fundamentals source (annual
statements + P/E/ROE). Filings ingestion is the primary truth but requires manual
uploads. Removing yfinance leaves filings as the sole fundamentals source unless a
replacement enrichment is added (clearly-labeled web-research enrichment is allowed
per the task brief, with caching/rate-limit/source tags).

## Reusable assets

- Upstox client/provider (solid, tested) — the foundation of the unified data layer.
- CompanyPreparationService — already the central per-symbol preparation flow;
  natural home for the Phase 2 Stock Context assembly.
- DuckDB repositories + provenance — unchanged by the restructure.
- All 5 agents — repository-only; only orchestration seams change.
- Frontend: FinCortextContext (session caches), CandleChart (custom SVG), PeerTable,
  AgentOutputCard/MacroOutputCard/PortfolioViewCard, StatusBadge, CompanySelector,
  the 4 agent pages (to be kept mounted-but-unlinked in Phase 4), styles.css
  design tokens (partial design system already in place).
- Tests: Upstox provider tests, contract tests, and the honest-state frontend tests.
