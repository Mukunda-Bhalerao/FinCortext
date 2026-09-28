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

### Milestone 10 — Product Polish + Navigation State ✅
**Navigation-state fix (root causes, not symptoms):**

- `App.tsx` rendered `<main key={location.pathname}>`, remounting every page
  on each route change. Removed — research state now lives in the session
  provider, not in mount lifetime.
- Company selection was split (Dashboard local state vs `?symbol=` on analyst
  pages). New `frontend/src/app/FinCortextContext.tsx` owns one selection,
  mirrored to `?symbol=` (header nav carries it; `localStorage` fallback).
- Backend reads (universe, prices, outputs history, news, market coverage) are
  cached per symbol per session with in-flight dedup — navigation never
  refetches. Fresh `AgentOutput`s are recorded into the run cache (and folded
  into the history cache) on production, so pages restore previous results with
  timestamps instead of re-running. Verified live: firm 59.2 DEGRADED/buy,
  industry 69.2 OK/buy (auto-prepared TCS+INFY), sentiment 56.9 OK/buy.

**Dashboard redesign (real data only):** company identity + sector meta, latest
close / day change / last-session OHLCV / stored-days KPIs, stored-OHLCV chart
with 1M–All range selector + volume bars, animated score rings per analyst,
combined scores, stored-news panel, sector peer table from universe +
`GET /api/market/status`, evidence strip (trading days · articles · ingested
filings). No index values (no index feed exists — none invented). Real logo +
tagline in header; footer/backend-version internals removed from demo UI.

**Docs:** README rewritten to the current build (32 sections, implemented /
partial / future split, no `.env.example` fiction — table is the reference);
ARCHITECTURE.md gained the session-state design, industry auto-preparation
section, and the vision-diagram scope note (`SystemArchitecture.jpeg` stays a
product asset in `frontend/src/utils/`).

### Milestone 11 — Multi-Company Analysis + Terminal Dashboard ✅

**Root cause of the multi-company problem (traced selector → analyst):**
the frontend flow was already symbol-generic — the gap was data + messaging.
Only TCS had the full trio (prices + outputs + news); RELIANCE/INFY had prices
but zero stored news (sentiment UNAVAILABLE); RELIANCE as a single-member
Energy sector scored industry UNAVAILABLE with a *wrong* diagnosis ("No
peer/company price data — refresh market data") despite 506 stored bars.
Fixed with real data (news refresh: 50 articles each for RELIANCE/INFY;
universe market refresh: all 10 symbols now hold ~500 LIVE bars) plus an
honest peer-less diagnosis in `IndustryAgent` (messaging only — methodology,
weights, availability logic unchanged) and product-worded sentiment guidance
(no endpoint names in analyst output).

**Dashboard redesigned as a market terminal:** company identity header
(symbol, name, ticker/sector/industry/exchange chips, price, day change,
freshness badge with LIVE-only pulse) → 6 market KPI cards (day high/low,
volume, day range, 30-day change, 90-day momentum — all from stored bars,
short windows render "—" when history is insufficient) → price/volume chart
with 1M/3M/6M/1Y/All → sector peers (click a peer to switch the terminal) +
recent stored news → analysis links (navigation only) → freshness strip.
Removed: analyst score rings/cards and Combined Intelligence duplication,
dead ring/analyst CSS, unused imports. No indices, no market cap, no invented
statistics anywhere.

**Tests:** backend 127 (new single-member-sector test pins peer-less wording,
evidence and unchanged UNAVAILABLE status); frontend 16 (terminal rendering
per company, selector switching TCS→INFY, RELIANCE single-member peers,
no-refetch on remount, Dashboard→all-four-analysts→Dashboard symbol
persistence with RELIANCE, localStorage isolation between tests).

### Milestone 12 — Sidebar Terminal + Company Analysis ✅

**Reference-driven frontend rebuild (no backend changes):** left sidebar with
logo + six demo destinations (Dashboard, Company Analysis, Firm/Industry/
Sentiment Analysts, Intelligence Summary); Data/Research sections removed from
the visible UI, routes stay mounted but unlinked. One global company search in
the topbar (filterable, keyboard navigable) feeds every page — page-level
selectors removed. Topbar freshness pill mirrors the real stored-series status
(LIVE-only pulse) plus the latest available trading date; no fake "live" claims.

**Dashboard** follows the reference layout with real data only: identity header
(price, day change, day high/low, volume, Analyze → Company Analysis), anchor
tabs, price-performance chart (1M/3M/6M/1Y/All), Market Context with real
stored peer quotes, compact stored intelligence (latest output per analyst +
detail links), recent stored news, and a Key Takeaway deterministically derived
from stored outputs (missing views reported, never hidden). No Nifty/indices,
no market cap, no blended scores — the backend provides none.

**New Company Analysis page** (`/company`): stored price statistics, data
inventory (prices/news/filings/analyst run history), sector peers. Shared
derivations extracted to `features/company/` (`priceStats` + unit tests,
`usePeerQuotes`, `useFilingsCount`, `PeerTable`).

**Company-selection reliability:** re-verified live (RELIANCE firm 56.0
DEGRADED, INFY sentiment 79.4 DEGRADED + firm 35.9 DEGRADED, RELIANCE industry
honestly UNAVAILABLE as single-member Energy sector). Frontend flow stays fully
symbol-generic; `FinCortextContext` hardened with ref-mirror caches so stale
closures after rapid switches can never duplicate a settled fetch (also
stabilizes callback identity → fewer effect re-runs).

**Tests:** backend 127 unchanged; frontend 24 (sidebar nav, search switching,
takeaway derivation incl. partial coverage, company page inventory, priceStats
unit tests, full Dashboard→all-pages→Dashboard persistence). Build clean.

### Milestone 13 — Reliability & Sentiment Relevance ✅

**Sentiment relevance overhaul (the major correctness fix):** provider search
returns anything mentioning the ticker — sponsored marathons, HR anecdotes,
tragedies, market digests, common-noun collisions ("weighing reliance on
Stripe"). New deterministic `relevance.py`: article counts only with BOTH a
company-identity hit (legal name / curated per-company `aliases` /
`ticker`, whole-word for single tokens) AND financial/business context
(`FINANCIAL_KEYWORDS`), never on excluded topics (brand sport, tragedies,
retail-promo acronym collisions). Plus former-affiliation guard (bio-line
"previously chairman of X" ≠ company news) and case-sensitive `strict_aliases`
(capitalized `Reliance` = company, lowercase = common noun); 2-letter symbols
never bare-match (`L&T`, not `LT`). Verified on live titles: TCS 10/58
relevant, RELIANCE 0/50 (honest UNAVAILABLE), INFY 1→2/50. Aggregation
methodology untouched; provenance now reports stored/relevant/rejected plus
per-reason breakdown, `latest_article_date`, and exclusion examples.

**Also fixed:** alias-aware NewsAPI queries (`default_news_query`; deduped);
`market_latest_date` in firm/industry provenance; frontend mid-flight guards
(runs record under their own symbol, never paint foreign results) with
entity-gated display (no stale frame on switch); canonical-uppercase symbols
in context; sentiment page shows stored-news status instead of a decorative
LIVE badge; output cards separate analysis time from data-through dates;
coverage indicator on Company Analysis (`Data coverage: X/3`, filings caveat).

**Tests:** backend 154 (27 new: relevance unit incl. real-world titles,
screening counts, aliases, query builder, peer-set switching, per-symbol firm
isolation, status semantics); frontend 36 (12 new: context isolation, no-stale/mid-flight
guards, side-by-side-no-blend, stored-news status, date lines, coverage).
Full 30/30 live matrix verified (correct entity_id everywhere). Build clean.

### Milestone 14 — Provider Fundamentals + Roadmap Skeleton ✅

**Fundamentals ingestion foundation (highest-priority data upgrade):** new
`YFinanceFundamentalsProvider` (annual income/balance statements + trailing
P/E + TTM ROE, normalized to canonical metrics) → validation (finite,
sane-sign, reported rejections) → `FundamentalsService` (per-symbol refresh
with failure isolation, refresh *replaces* the previous provider snapshot via
scoped delete, official filings never touched) → `FinancialObservation`s with
full provenance → existing Firm Analyst (unchanged scoring) → API
(`POST /api/fundamentals/refresh[/{symbol}]`, `GET /api/fundamentals/{symbol}`
coverage with per-metric source labels). Source honesty: `source_type=yfinance`,
never official filings; snapshot ratios carry no statement period
(`available_at` = ingestion, stated limitation). Live ingestion: 10/10 symbols,
all Firm Analysts moved from momentum-only DEGRADED to data-supported
(e.g. TCS 79.5 OK 6/6, INFY 75.3, ITC 79.5); industry peer fundamentals
unlocked (TCS industry 4/4). Also fixed a real read-path bug the new data
exposed: the agent's global-period filter silently dropped period-less
snapshot metrics (and older-vintage metrics) — each metric now uses its own
latest observation (formulas untouched).

**Roadmap skeleton:** `/roadmap` page + sidebar Expansion section with grouped
Under-Development cards (Portfolio & Optimization, Evaluation, Asset Coverage,
Research) — scope text only, zero fabricated metrics.

**Frontend:** Company Analysis gains a Fundamentals inventory row (metric count,
official vs provider source labels, latest period); Firm Analyst prerequisites
describe both sources.

**Tests:** backend 172 (+18: provider normalization, validation rules, service
flow incl. refresh-replace/partial-data/isolation, firm mixed-vintage); frontend 41
(+5: roadmap skeleton, fundamentals coverage row). Full suites + build clean;
live 10-symbol matrix re-verified.

### Milestone 15 — Macro Analyst ✅

**Market-wide environment intelligence (no new architecture):** curated RBI/MoSPI
history (repo-rate decisions, CPI months, GDP quarters — every value verified
against official releases, per-row source URLs) + yfinance market gauges
(USD/INR, Brent, US 10Y, India VIX; Nifty deliberately excluded to keep macro
strictly macro) → validation → `MacroService` (per-indicator isolation,
provenance) → DuckDB `macro_observations` (point-in-time: period vs
publication vs available dates; deterministic ids) → deterministic 7-factor
engine (documented benchmarks: 7% potential GDP, RBI 4±2 band, MPC step sizes,
materiality floors, majority votes) → `MacroAgent` → dedicated `MacroOutput`
contract (`MACRO_INDIA`, POSITIVE/NEUTRAL/NEGATIVE, no numeric score).
Liquidity/credit and fiscal feeds honestly unavailable (never proxied);
fact-vs-interpretation labeled in rationale. Runs via standard
`POST /api/agents/macro/{symbol}/run` (symbol validated as context, result
identical); reads via `/api/macro/*`. Frontend: Macro Analyst page, 4th
summary perspective (no blending), dashboard macro strip, sidebar nav.
Live: 7/7 indicators ingested, macro signal NEUTRAL (conf 0.81), deterministic
across symbols.

**Tests:** backend +25 (methodology math, validation, curated-CSV guards,
provider normalization, agent OK/DEGRADED/UNAVAILABLE paths, determinism,
symbol-independence, API contract); frontend +3 (macro page states, switching
persistence, summary integration) with dashboard strip assertions. Full suites
+ build clean; live verified against real data.

### Milestone 16 — Macro Score + Portfolio Synthesis ✅

**Macro Environment Score (frontend parity, no methodology change):** the
backend already computed `score = 50 + 50·net/n` over available factors only
(with signal agreement by construction, unavailable areas excluded, and
cross-factor evidence dedup). This milestone surfaces it consistently: the
Macro card now shows `Macro Environment Score: XX / 100` + `Signal:
POSITIVE/NEUTRAL/NEGATIVE` + `Status` + `Confidence: XX%` with a numeric dial
(the cryptic `NEU` badge and a duplicated signal badge are removed); the
Dashboard strip and Intelligence Summary show the score; docs
(`docs/macro_methodology.md`, `ARCHITECTURE.md`) now describe the score and
its no-blending rule.

**Portfolio / Central Orchestrator (synthesis UI + production wiring):** the
backend synthesis (`PortfolioAgent`, methodology, `PortfolioView` contract,
repository, `AgentService.run_portfolio`, routes) already existed but was
unreachable in production — `Container` never passed `portfolio_repo` into
`AgentService`, so `POST /api/agents/portfolio/{symbol}/run` always 404'd.
One-line wiring fix; no methodology changes. New frontend: `PortfolioView`
types + `api.portfolio` (run/latest/history), `PortfolioViewCard`
(perspectives, agreement/conflicts, thesis, evidence, risks, scenarios,
rationale, limitations, coverage/confidence), `PortfolioSynthesisPage`
(`/portfolio`, per-company stored view + fresh runs, symbol-guarded, macro
labeled market-wide), sidebar `Portfolio Synthesis` entry, concise Dashboard
link (no full outputs on the Dashboard), Company Analysis + Summary links.

**Tests:** backend 213 → 220 (+7: wiring, end-to-end synthesis, TCS/INFY/
RELIANCE isolation, DEGRADED flagging, score/signal agreement, explicit
dedupe unit test); frontend 44 → 52 (+8 portfolio page tests: agreement,
conflicts, missing/DEGRADED, market-wide macro, TCS/RELIANCE/INFY, switching,
URL persistence, errors; macro/summary/dashboard/app tests updated for the
score presentation). No existing assertions weakened — score-display tests
were updated to the new specified behavior. Full suites + build clean.

### Milestone 17 — Portfolio Synthesis decision-support layer + final polish ✅

**Decision-support rebuild (frontend only — no backend or methodology
changes):** `PortfolioViewCard` rebuilt around a fixed visual hierarchy —
four distinct perspective cards (score/signal/confidence/status each; Macro
headed "Market Environment" with the bare signal, dashed styling, market-wide
warning, "Open Macro Analyst →" link) → Investment Thesis panel (positive/
neutral/negative count badges, strongest-supported + most-uncertain views
derived from perspective confidences, disagreements, evidence-based thesis
wording, rationale folded in as "Why this interpretation") → Base/Bull/Bear
scenario cards (explicit Base→Bull→Bear order, analyst tags derived from the
backend's own condition wording; conditional, never predictive; no
probabilities or price targets) → collapsible Supporting evidence / Key risks
(grouped by analyst, exact-dupes removed) / Limitations sections. Per-card
analyst links + "← Back to Dashboard" preserve `?symbol=`; company switching
(TCS/INFY/RELIANCE) reloads that company's own synthesis with no stale
frames.

**Final polish pass:** the backend always appends one generic synthesis
disclaimer, which rendered as an empty-looking "Limitations (1)" section —
now display-filtered so Limitations renders only for genuine warnings;
perspective cards dropped the takeaway sentence that restated the fact grid
(takeaway kept for `missing` perspectives only); the card header no longer
repeats the agreement sentence (counts live once in the thesis panel).
`frontend/src/app/styles.css` gained a small portfolio section reusing theme
variables/badges/cards (no charts, no decoration).

**Tests:** backend 220 unchanged (no backend changes); frontend 52 → 60
(+8 portfolio page tests: macro-card distinction, analyst/dashboard link
hrefs, agreement counts + strongest/weakest, conditional scenario cards,
collapsible grouped evidence/risks, RELIANCE partial coverage, TCS→INFY→
RELIANCE switching, empty-vs-genuine Limitations cases, macro market-wide
independence, URL persistence, errors). Full suites + build clean.

### Milestone 18 — Upstox Analytics + Central Company Preparation ✅

**Live market data without rebuilding the project:** `UpstoxHttpClient` /
`UpstoxMarketProvider` (instrument search, full quotes V3, historical candles
V3; NSE-equity filter; `instrument_key` canonical; yfinance kept as honest
fallback that can never overwrite newer Upstox data) behind
`LIVE_MARKET_PROVIDER=upstox`. `CompanyPreparationService` runs the single
SEARCH → PREPARE → STORE → AGENTS flow per selection (resolve → quote →
history → fundamentals → news → peers) with per-area statuses and overall
`ready`/`partial`/`unavailable` readiness (`POST /api/market/prepare/{symbol}`,
`GET /api/market/prepared/{symbol}`, `GET /api/market/peers/{symbol}`).
Dynamic equities register without touching the static 10-symbol universe;
configured peers first, then curated same-sector candidates validated live
via Upstox (exact-listing gate — fuzzy rows like BSE-for-LTIM are skipped).
Live quote snapshots persist in `market_quotes` (newer-wins, Upstox priority)
so the UI freshness timestamp is the actual Upstox timestamp with
`Source: upstox`. Frontend: Upstox search in the selector, quote-preferred
values with `N/A` gaps, preparation strip, freshness pill.

### Milestone 19 — Gemini Web Research + Readiness Components + DB Lock Fix ✅

**Root causes fixed:** (1) ADANIPOWER stayed "Unknown" because nothing could
classify dynamic equities — now grounded Gemini research fills sector/industry
(stored with sources + confidence, applied only when usable) and suggests
peers Upstox then validates. (2) ADANIPOWER news was empty because the quoted
full-legal-name query missed "Adani Power" phrasing — preparation now tries
company-name variants (default → short name → symbol/business context) plus a
labeled Gemini digest fallback (research evidence, never articles, never
FinBERT-scored). (3) `prepare` returned 200 with no per-consumer signal — now
a `components` block (market/fundamentals/company_metadata/industry/peers/
news/web_research → READY/PARTIAL/UNAVAILABLE) drives the frontend strip.
(4) Startup `TransactionContext ... Conflict on update!` and quote
`ConstraintException`: repository writes bypassed the storage RLock via raw
`connect().execute()` — all 8 sites now go through locked `execute`/
`executemany`/`transaction()` helpers, with a threaded regression test.
Gemini is research-only (classification, peers, digests, evidence) behind
`ResearchProvider`/`ResearchService` + `research_reports`; deterministic
finance untouched. Live-verified: ADANIPOWER `ready` for market/fundamentals/
news; Gemini itself degraded honestly (configured model retired for the key +
quota exhausted — structured paths kept working).

### Milestone 20 — Gemini SDK Migration + Honest Readiness + Startup Sync ✅

**Exact 404 cause:** the hand-rolled REST call hit
`v1beta/models/gemini-2.5-flash:generateContent`, which this key answers with
"no longer available to new users" — while `models.get` on the same id
succeeds, so metadata checks alone cannot verify a model. Rewrote
`GeminiResearchProvider` on the official `google-genai` SDK
(`genai.Client(api_key=...)`, `GenerateContentConfig` with JSON schema +
`google_search` tool, key header-only, never logged). Sanitized per-class
diagnostics now distinguish invalid key ("check GEMINI_API_KEY"), retired
model ("... is not available for this API key/project. Set GEMINI_MODEL ..."),
rate limit, endpoint error, timeout, and safety blocks — all observed live
except timeout/safety (unit-covered). `verify_model()` performs a real minimal
generation (not a metadata lookup) and backs `GET /api/research/verify`;
`GEMINI_MODEL` stays `.env`-configurable, no hardcoding.
**Readiness honesty:** backend `ready` now requires market + fundamentals +
metadata + peers + news (was quote+history only); the frontend strip says
"Company data ready" only when market/fundamentals/company-info are READY,
otherwise names exactly what is ready vs unavailable. **Startup sync:** repeat
startups perform zero writes (skip-when-in-sync on static entries at the
current version) and genuine write races retry with backoff; non-transient
errors still raise. Live-verified: BBL prepare returns `partial` with
market/fundamentals/news READY and the exact model diagnostic (not "HTTP
404"); enrichment E2E awaits quota reset (mocked trace proves research peers
land in the Industry Analyst's `peers_with_prices`).

### Milestone 21 — Free Industry + Sentiment for Any NSE Stock (No Gemini) ✅

**Root causes fixed without any paid API or Gemini dependency:** (1) NewsAPI
free tier returns little usable Indian-stock news (RELIANCE was 0/50
relevant) — new `GoogleNewsRssProvider` (Google News RSS search with
short→full→symbol query variants stopping at ≥5 items, Yahoo Finance
headlines RSS fallback inside the same provider, stdlib ElementTree parsing,
browser UA, ≤1 req/sec, retries, 6h cache) is now the keyless default
(`NEWS_PROVIDER=google_rss`); NewsAPI stays as an optional secondary merge
source with storage-level dedup. (2) `relevance.py` needed hand-curated
aliases per company — new `generated_aliases()` derives identity patterns
from any company name (suffix-stripped short forms, first-two-words,
`&`/`and` variants, symbol), curated aliases keep priority, single
common-noun words stay strict, financial-context gate untouched.
(3) Dynamic equities stayed "Unknown" without Gemini — new
`IndustryClassifier` resolves ANY symbol via static universe → official NSE
Nifty 500 industry list (committed CSV + `scripts/refresh_industry_universe.py`)
→ yfinance metadata → Gemini last resort → honest Unknown; same-industry CSV
symbols feed peer discovery through the unchanged Upstox exact-gate +
`ensure_history` validation. Scoring methodologies, weights, and the
`AgentOutput` contract are byte-identical.
**Tests:** RSS parsing (suffix/HTML/pubDate), variant order + stop rule,
Yahoo fallback + dedup, cache hit/expiry, retry→`ProviderError`, service
merge/rescue/error paths, per-stock alias positive+negative cases
(RELIANCE/ADANIPOWER/TATAMOTORS/HDFCBANK/ZOMATO/TITAN + `&` forms),
classifier order (universe/CSV/ISIN/yfinance/unknown/missing-file), peer
exclusion/cap/BE-filter, end-to-end prepare→industry+sentiment for NHPC
(outside the original 10, no Gemini, no curation). Agent runs resolve renamed
symbols canonically (`AgentService._canonical_symbol`: ZOMATO→ETERNAL,
TATAMOTORS→TMCV via the market service; unknown symbols still 404; scoring
untouched), so renamed/demerged listings work from any entry point, not just
the selector. New suites run green during development (19 RSS, 12 classifier,
29 relevance, 29 preparation incl. NHPC e2e); final full-suite re-runs skipped
per instruction — run `pytest` + `npm test` before the demo.

**Live acceptance (real network + keys, 2026-09-29; honest UNAVAILABLE kept
where data genuinely ends):**

| symbol | industry + source | #peers used | #articles stored/relevant/rejected | industry score | sentiment score |
|---|---|---|---|---|---|
| RELIANCE | Integrated Oil & Gas (universe) | 4 (BPCL, COALINDIA, GAIL, IOC) | 100 / 16 / 84 | 43.7 OK | 42.1 OK |
| ADANIPOWER | Power (nse_nifty500_csv) | 4 (ACMESOLAR, ADANIENSOL, ADANIGREEN, CESC) | 58 / 36 / 22 | 46.1 OK | 56.6 OK |
| TATAMOTORS → TMCV | Capital Goods (nse_nifty500_csv; post-demerger NSE mapping) | 4 (ABB, ACE, AIAENG, APARINDS) | 50 / 40 / 10 | 52.1 OK | 46.7 OK |
| HDFCBANK | Private Sector Bank (universe) | 2 (ICICIBANK, SBIN) | 100 / 58 / 42 | 57.9 OK | 41.5 OK |
| ZOMATO → ETERNAL | Consumer Services (nse_nifty500_csv; renamed listing) | 4 (ABFRL, ABLBL, BLS, CARTRADE) | 67 / 32 / 35 | 62.0 OK | 60.5 OK |
| TITAN | Consumer Durables (nse_nifty500_csv) | 4 (AMBER, ASIANPAINT, BATAINDIA, BERGEPAINT) | 56 / 40 / 16 | 67.4 OK | 54.4 OK |

All six score OK on both analysts with real Upstox-validated peers and
FinBERT-scored relevant articles — no Gemini, no paid API, no invented data.

## CURRENT STATE

- Backend: 325 tests passing. Market pipeline, filing ingestion, provider
fundamentals (labeled fallback), macro indicators (curated official +
market gauges) with environment score, Firm Analyst, Industry Analyst, Macro
Analyst, Portfolio synthesis, and News+Sentiment all working offline
(fixtures/fakes; live providers network-optional). Sentiment relevance is
a deterministic identity+financial-context screen with auditable
stored/relevant/rejected counts (see Milestone 13).
- Upstox Analytics is the primary market provider (`LIVE_MARKET_PROVIDER=upstox`);
  yfinance remains as honest fallback. Central company preparation warms every
  repository analysts read; dynamic equities resolve without static-universe edits.
- Gemini web research enriches unknown metadata, suggests peers (Upstox-validated),
  and digests news gaps — evidence-only, confidence-gated, honestly degraded
  when unconfigured or quota-exhausted.
- Market data canonical-key invariant enforced: stored bars are keyed by the
internal symbol (TCS), never the provider ticker (TCS.NS); startup repair
re-keys any legacy rows (see "Bugfix — Market data canonical symbol key").
- Firm/Industry agents report DEGRADED (not OK) when a score rests on less
than half of the documented factor weight.
- Industry Analyst auto-prepares its market data (company + sector peers):
fresh cached history is reused, only missing/stale symbols are fetched.
- Demo navigation: Dashboard, Company Analysis + the four analysts (Firm,
Industry, Macro, Sentiment) + Intelligence Summary + Portfolio Synthesis in
the sidebar, plus an Expansion section with the Roadmap skeleton;
all other pages remain mounted at their routes but are unlinked.
- Frontend: 61 component tests passing; production build clean. Preparation strip
  shows per-component READY/PARTIAL/UNAVAILABLE; Sentiment page shows labeled
  web-research context when NewsAPI has nothing usable.
- All implemented agents emit via `POST /api/agents/{agent}/{symbol}/run`
(company analysts → `AgentOutput`; macro → market-wide `MacroOutput` with
environment score; portfolio → per-company `PortfolioView` synthesis, no
overall score).

## TEST STATUS

- `cd backend && python -m pytest` — **325 passed** (incl. 18 SDK-mocked Gemini
  provider tests with the BBL research task, research-backed preparation
  scenarios, sync skip/retry tests, DuckDB concurrency test, 19 Google News
  RSS tests, 12 industry-classifier tests, 10 auto-alias tests, NHPC
  end-to-end prepare→industry+sentiment)
- Frontend `npm test` — **61 passed** (sidebar nav incl. portfolio synthesis,
  macro page/summary/dashboard-strip, company search/switching, takeaway
  derivation, company page inventory (incl. fundamentals coverage), context isolation,
  company search/switching, takeaway derivation, company page inventory
  (incl. fundamentals coverage), context isolation, no-stale/mid-flight
  guards, side-by-side-no-blend, stored-news status, date lines, coverage
  indicator, priceStats unit tests, full Dashboard→all-pages→Dashboard
  persistence, no-refetch, localStorage isolation, portfolio perspective
  cards/thesis/scenario/evidence-risk rendering, macro Market-Environment
  presentation, empty-vs-genuine Limitations, analyst/dashboard navigation)
- Frontend `npm run build` — passing

## KNOWN LIMITATIONS

- Live yfinance/NewsAPI untested in CI (network-dependent; adapters covered
  by fakes/mocked HTTP).
- `POST /api/market/refresh` is synchronous — 10 symbols take ~10-30s live.
- PDF parsing is explicitly a limited fallback (documented in results).
- Firm Agent needs ≥2 price points for momentum; single-period filings leave
  revenue_growth unavailable (by design — no fabrication).
- Industry Analyst peers: configured universe → curated same-sector candidates →
  official NSE-industry CSV peers → Gemini suggestions, each validated live
  via Upstox (exact-listing gate) with real history before counting. Sectors
  that cannot be established from any source honestly report unavailable peer
  factors (docs/industry_methodology.md).
- News default is keyless Google News RSS (+ Yahoo fallback); NewsAPI merges
  as secondary only when configured. RSS items carry Google's title/source
  parsing and a 6h cache; relevance still requires identity AND financial
  context, so recall gains never become scored noise.
- Gemini research needs a key whose model id is available with quota; a retired
  model id or exhausted quota degrades research to UNAVAILABLE with the reason
  stated (structured providers unaffected). Low-confidence classifications are
  stored as evidence but never applied.
- FinBERT downloads on first sentiment run (~440MB) into
  `data/cache/sentiment-model`; until then sentiment reports UNAVAILABLE.
- Sentiment relevance is a deterministic identity + financial-context screen
  (see Milestone 13); lexical matching may miss indirect references, and bare
  short brand tokens have documented recall trade-offs. NewsAPI free tier
  caps history (~30 days).
- Macro curated series are manually maintained (no live RBI/MoSPI feed is
  reachable from here); liquidity/credit and fiscal feeds are honestly
  unavailable; market gauges need ~1 quarter of history before voting.

### Bugfix — Market data canonical symbol key ✅

**Symptom:** `POST /api/market/refresh/TCS` reported "501 stored, 0 rejected"
while the frontend Market Data page showed "0 stored bars / UNAVAILABLE" and
the Firm/Industry Analysts reported missing price data.

**Root cause:** `MarketService.refresh_symbol` passed the provider ticker
(`TCS.NS`) to `YFinanceMarketProvider.fetch_ohlcv`, which keyed every stored
bar's canonical `symbol` field with that provider ticker. DuckDB rows were
therefore stored under `symbol='TCS.NS'`, while every read path
(`GET /api/market/prices/{symbol}`, `/api/market/status`, Firm Agent momentum,
Industry Agent peer metrics) queries the internal symbol (`'TCS'`) — zero rows
found. The integration test's fake provider masked the bug by stripping the
`.NS` suffix itself (`symbol=ticker.split(".")[0]`).

**Fix (canonical-key invariant):**
- `MarketService.refresh_symbol` now requests the **internal symbol**; the
  provider resolves the provider ticker via the universe mapping (as its
  container wiring always intended).
- `YFinanceMarketProvider` hardens the boundary: bars are keyed by the
  canonical internal symbol even if a provider ticker is passed directly
  (reverse mapping), matching `MarketPrice.symbol`'s documented meaning.
- `MarketRepository.normalize_symbol_keys()` (wired idempotently into
  `Container.__init__`) re-keys rows historically stored under provider
  tickers to internal symbols — real price data preserved, exact duplicates
  by `(symbol, trade_date)` removed. First startup re-keyed 1002 rows.
- Firm/Industry agents now emit `status="DEGRADED"` when a score is computed
  from less than half of the documented factor weights (e.g. momentum only,
  no filings) — a 200 response is never presented as a fully-successful
  analysis when the underlying required data is missing.

**Tests added:** service stores/reads under the internal symbol; provider
reverse-resolution (both call styles); key-repair migration (incl. dedup);
firm agent thin-evidence DEGRADED. Frontend: fixed two pre-existing ambiguous
`getByText` queries (duplicate rendered text) and added a DEGRADED badge test.

### Milestone 9 — Demo Readiness ✅

**Industry Analyst automatic data preparation:**
- `MarketService.ensure_history(symbols, min_bars, max_age_days=7)`: per
  symbol, sufficient **fresh** cached history (≥ `MIN_PRICES_FOR_METRICS`
  bars, latest trade date within the 7-day LIVE window) is reused as-is —
  the provider is not called. Missing/stale symbols go through the normal
  refresh pipeline (provider → validation → storage → provenance). Provider
  failures are isolated per symbol (`refresh_failed`) and never raised, so
  the analysis still runs on cached data with honest limitations.
- `AgentService` (optional `market_service`, default `None` — existing
  constructions unaffected) prepares sector peers via `get_sector_peers`
  before every `industry_analyst` run and records a transparent
  `data_preparation` summary (cached/refreshed/failed per symbol) in the
  output provenance. Agents stay repository-only (no provider coupling).
- Tests: cache-hit no-fetch, fetch-only-missing, stale-refresh, provider
  failure isolation (MarketService); industry flow auto-fetches missing
  peers then re-runs purely from cache; failure path still analyses cached
  company data.

**Demo UI cleanup (routes and backend functionality untouched):**
- Main navigation reduced to Overview → Dashboard and Intelligence →
  Firm/Industry/Sentiment/Combined Summary. Data, Macro, Portfolio and
  Research pages remain fully mounted at their routes (pinned by new
  `App.test.tsx` navigation + hidden-route tests) — only unlinked.
- Dashboard replaced with a product-oriented overview: platform intro,
  company selector, "Analyze Company" primary action, the three analyst
  modules and Combined Summary access. No backend paths, DB/cache/config
  diagnostics or "coming soon" lists (backend status endpoints remain).
- Intelligence pages: selected company carried via `?symbol=` across the
  demo flow; developer wording (repo paths, env-var names, manual data-page
  instructions) replaced with product copy; honest statuses, evidence,
  limitations and methodology reporting kept unchanged.

## NEXT RECOMMENDED STEP

Next candidates: risk/constraint engine + weight optimization on top of the
now-reachable `PortfolioView` contract (Roadmap "Portfolio Construction");
evaluation harness (backtesting on the preserved point-in-time metadata).
Macro data maintenance stays manual (curated CSV versions) until a reachable
official feed exists.
