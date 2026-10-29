# FinCortext

Research terminal for NSE-listed equities. A FastAPI backend pulls market data from Upstox,
caches it in DuckDB and relays live prices to a React dashboard. See `PLAN.md` for the roadmap
and `AGENT.md` for coding conventions.

## Setup

Requirements: Python 3.11+, Node 20+.

```bash
# backend
cd backend
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"      # macOS/Linux: .venv/bin/python

# frontend
cd ../frontend
npm install
```

`uv sync` also works if you use uv. No credentials are needed to install or start the app.

## Connect Upstox

**Simplest: Analytics Token.** Generate an Analytics Token in the Upstox developer console
(read-only, valid for one year) and put it in `UPSTOX_ACCESS_TOKEN` in `.env`, then restart
the backend. It covers quotes, candles, market status and the live WebSocket feed. It cannot
read account details (`user_name` stays empty) and cannot trade. The expiry shown in
`/api/auth/status` is read from the token itself.

**Alternative: daily OAuth sign-in.**

1. Create an app at <https://account.upstox.com/developer/apps>. Set its redirect URL to
   `http://localhost:8000/api/auth/upstox/callback` (must match `UPSTOX_REDIRECT_URI` exactly).
2. Copy `.env.example` to `.env` in the repository root and fill in `UPSTOX_API_KEY` and
   `UPSTOX_API_SECRET`.
3. Start the app and click **Connect Upstox** in the top bar. After you sign in, Upstox
   redirects back and the backend stores the token in the local DuckDB file.

Upstox access tokens expire daily (03:30 IST). When that happens the app shows
**Connect Upstox** again. Alternatively, paste a token generated on the developer dashboard
into `UPSTOX_ACCESS_TOKEN`. A token from the in-app sign-in takes precedence.

Secrets and tokens stay on the backend. They are never sent to the browser or written to logs.

## Run

```powershell
./dev.ps1
```

Or in two terminals:

```bash
cd backend && .venv/Scripts/python -m uvicorn app.main:app --reload --reload-dir app --timeout-graceful-shutdown 2 --port 8000
cd frontend && npm run dev
```

Open <http://localhost:5173>. The Vite dev server proxies `/api` (including the WebSocket)
to the backend.

## Verify

```bash
cd backend && .venv/Scripts/python -m pytest -q     # parsing, market hours, API and security checks
cd frontend && npm test && npm run build            # live-candle logic, strict type check, bundle
```

`GET http://localhost:8000/api/health` reports the instrument master, Upstox connection,
live feed and market session state.

## How data flows

| Data | Source | Notes |
|---|---|---|
| Instrument master | Upstox `NSE.json.gz` / `BSE.json.gz` | Downloaded daily; all instrument keys (including index keys) are resolved from it |
| Quotes | Upstox `/v2/market-quote/quotes` | Batched (500 keys), cached 5 s in session, 2 min after hours |
| Candles | Upstox V3 historical + intraday candle API | Completed sessions merged with the current session; cached in DuckDB |
| Live prices | Upstox Market Data Feed V3 (protobuf WebSocket) | One upstream connection, subscriptions only for instruments on screen |
| Market session | Upstox feed status, then `/v2/market/status/NSE`, then the weekday timetable | Timetable fallback is labelled and does not know holidays |
| NIFTY 50 constituents (movers) | NSE public CSV | Mapped to instruments by ISIN |
| Headlines | Economic Times, Business Standard, Mint RSS | Headline, link, publisher and time only |
| Industry, peers, candidates | NSE NIFTY 500 and NIFTY 100 constituent CSVs | NSE industry per company; peers are the 12 most traded members of the same industry |
| Fundamentals, analyst consensus | Yahoo Finance quote summary (unofficial) | Cached 24 h; every field optional, missing fields become data gaps |
| Macro series | FRED CSV: India 10Y yield, USD/INR, Brent, US 10Y, India CPI | Cached 12 h; observations past their freshness window are shown but not scored |
| Company news | Google News RSS search | Last 30 days, filtered to headlines naming the company, cached 1 h |

Every displayed price carries a state: **Live** (streamed tick), **Polled** (REST polling
fallback), **Stale** (no update for 2 minutes while the market is open), **Last close**
(market closed) or **Unavailable**.

If the streaming feed cannot be established three times in a row, the backend falls back to
polling quotes every `POLL_INTERVAL_SECONDS` and retries the stream after five minutes. Set
`LIVE_MODE=poll` to use polling only.

On charts, the last candle follows received trades during market hours: intraday candles
update or roll over at the window boundary, the daily candle uses the provider's day volume,
and weekly or monthly candles only update the current period. Provider candles replace
tick-derived ones on the next refresh (every minute for intraday timeframes).

## Live prices and charts

One Upstox market-data WebSocket ("full" mode) is shared by every browser tab; the backend
reference-counts subscriptions and subscribes everything referenced once the socket is open, so
keys requested during connection setup are never lost. A key the provider has not answered
within 8 seconds is subscribed again (three times) and then reported as silent.
`GET /api/live/diagnostics` shows per-instrument message counts, silent keys and measured
latency; `python scripts/feed_probe.py 60` measures it from a client's point of view.

Measured during a market session (29 Oct 2026, 13:00-13:40 IST): exchange trade to browser
p50 0.56 s, p90 1.1 s, clock-corrected using Upstox's own server timestamps. Almost all of it
is provider side: full mode sends updates at intervals (NIFTY 50 about every 0.15 s, liquid
stocks about every 0.6 s, thinly traded stocks every few seconds). Backend to browser is 2-4 ms.

Charts keep your zoom and position: provider refreshes update the last bars in place (or restore
the exact window when older bars change), new candles move the view only when the latest bar is
on screen, and resizing (full screen, sidebar) keeps the same time window. Drag to pan, wheel to
zoom, drag an axis to scale it, Shift+drag (or the box tool) to zoom into a range; "Latest"
returns to the newest candle. Tools: measure (change, % and bars), horizontal price lines (saved
per instrument), magnet crosshair, reset view, full screen (Esc to leave).

5s, 15s and 30s candles are built in the browser from streamed updates the backend has recorded
since the instrument was first subscribed (`GET /api/live/ticks`); there is no earlier seconds
history, and prices between feed updates are not known, so brief extremes can be missed. Upstox
historical candles start at one minute.

## Research engine

Four agents score each stock from −1 to +1 with a confidence and coverage figure, the evidence
behind every factor (metric, value, source, as-of time) and a list of data gaps:

| Agent | Scored factors | Reported as gaps |
|---|---|---|
| Firm | Valuation and margins vs peer median, ROE, growth, debt/equity, price trend and momentum | ESG (no free source) |
| Industry | Sector index vs NIFTY 50, sector trend, 6-month return rank among peers, peer breadth | Demand and outlook |
| Macro | Rates, rupee, crude, US yields, inflation, NIFTY trend, India VIX, sector sensitivity rules | Policy and event calendar |
| Sentiment | Recency-weighted headline tone (word list in `tools/headlines.py`), analyst consensus, target gap | Social media |

All numbers come from deterministic code in `backend/app/tools` and `backend/app/agents`. The
composite is the confidence-weighted mean of the agents that had enough data. Adding a stock to
the watchlist queues a run; a scheduler re-runs watchlist reports older than six hours (30
minutes if the previous run could not score). `POST /api/research/{symbol}/run` forces a run for
any stock. Signals summarise evidence; they are not forecasts or recommendations.

## Portfolio intelligence

The Portfolio page leads with a **brief**: a one-line headline and ranked insights (risks,
options, track record, research changes, data gaps). Every insight cites numbered facts, and
each fact names its source and whether it is *measured* (backtest), an *estimate* (trailing-year
risk model), a *replay* (today's weights through a past episode) or *observed* (a stored
research reading).

**Objectives and plans.** `POST /api/portfolio/plan` builds a plan for one objective (Lower
risk, Balanced growth, Aggressive growth, Dividend income) from the watchlist, minus any stocks
left out, plus any stocks being tried. Changing the objective, the maximum weight per stock, the
amount, or the stock set re-plans in about a second. A plan returns weights with plain-language
reasons, a risk level against the NIFTY 50, a diversification score, a walk-forward backtest,
stress replays (COVID-19 crash, 2022 rate-hike sell-off, late-2024 correction, the worst month in
the data) and the trades to get there from cash or from your holdings (`/api/portfolio/holdings`,
stored locally). Each objective's weights depend only on trailing data, so the backtest rebuilds
them on every past rebalance date; the optional research overlay applies to today's weights only.

**Backtesting V2** (`app/tools/backtest.py`):

- ten years of Upstox daily closes plus cash dividends from Yahoo Finance (total return);
- monthly rebalancing from cash, weights from the 252 sessions before each rebalance only;
- itemised NSE delivery costs (STT, stamp duty, exchange, SEBI, GST, DP charge, assumed 0.05%
  slippage) and an after-tax run (STCG 20%, LTCG 12.5% above Rs 1.25 lakh, FIFO lots, dividends
  at your slab);
- benchmark: the NIFTYBEES ETF as a NIFTY 50 total-return proxy (price index as fallback);
- uncertainty: a moving-block bootstrap of the excess return over the benchmark;
- bias controls: a selection check against 200 random same-size NIFTY 100 portfolios, and
  out-of-sample re-tests of the top diversification candidates on an earlier period.

Stocks are still chosen today, so every backtest carries survivorship and selection bias; the
page says so beside the results.

**Research history.** Every research run is stored (older days keep their last run).
`GET /api/research/{symbol}/history` returns the score trend and what changed since about a day
ago; fundamentals are also snapshotted daily so later backtests can use what was known then.

**Research validation.** `GET /api/research/validation` (the *Track record* panel on the
Research page) tests whether the agents' scores lined up with later returns. Once a week it
replays the unchanged Firm, Industry and Macro agents on each month's first session since late
2017 across the NIFTY 500 (in a separate process, about five minutes), using only data dated on or before that session: price windows, FRED
observations old enough to have been published, and annual statement ratios 75 days after year
end. Each score is compared with the next 21 sessions' return (rank correlation, block-bootstrap
interval, both halves of the history, top fifth versus universe after costs) against verdict
rules fixed in advance. Sentiment (no headline or analyst-rating archive) and valuation multiples
(unadjusted per-share history) cannot be replayed; stored live reports are tracked forward
instead. Each weekly run also records that day's scores before their outcomes exist, a forward test that builds up over time.
Current result: no agent or factor has shown reliable predictive value, so the research
nudge to portfolio weights is off by default.

**Goals, scenarios and alerts.** `POST /api/portfolio/goal` resamples a plan's own after-tax
monthly history into a range of outcomes for a target amount and date, labelled as a hypothesis,
next to the same calculation on the NIFTY 50. The workbench can pin one plan and compare it line
by line with the next. Every plan's backtest is also split into halves to show whether it held up
in both. A watcher (`/api/events`, the bell in the top bar) records research views that changed,
unusually large moves in your stocks, drift from your plan, risk piling into one stock, a new best
diversifier, failing data sources and new validation results, each with its evidence.

**Your holdings.** `GET /api/portfolio/summary` values your holdings at the latest price with
cost, P&L, today's change, weights and drift from the chosen plan; stocks you hold are always
part of the plan even when they are not on the watchlist. `POST /api/portfolio/holdings/sync`
reads Upstox long-term holdings (read-only; FinCortext never places orders). This needs a
token from the Upstox login (`UPSTOX_API_KEY` and `UPSTOX_API_SECRET`, then Connect Upstox):
an Analytics token is market-data only and Upstox refuses it holdings, which the app reports.
Hand-entered holdings work either way; synced rows replace only earlier synced rows.

**Analyst.** `POST /api/assistant/ask` first routes the question without the model: what-if
changes (add, drop, swap, "INFY at 15%", switch objective), comparing objectives, why a stock
did what it did (split into market, sector and stock-specific parts), and goals ("50 lakh in
10 years adding 10k a month", with the monthly amount needed for even and three-in-four odds).
The engine computes the answer; the model, when on and within budget, explains it from the
computed facts, and its output is rejected if it adds numbers. Offline, over budget, timed out
or malformed, the engine's own answer is shown, so the analyst works without the model.
Scenarios can be applied to the plan and undone.

**Alerts.** The watcher also notices new quarterly results, the NIFTY 50 crossing its 200-day
average, India VIX jumps and a 5% weekly fall in your holdings. Alerts carry a priority; the
same kind of alert for the same stock waits out a cooldown unless it is more severe, and at
most six non-urgent alerts appear per day.

**Optional language model.** With `LLM_PROVIDER=ollama` the brief gets a written note and the
page gets an assistant (`POST /api/assistant/ask`) that answers only from the computed facts,
cites them, and can turn a what-if question into a scenario the plan applies. Any output with a
number that is not in the facts (beyond rounding) is rejected. A signed-in local Ollama can route
a free-tier cloud model such as `gpt-oss:120b-cloud`; results are cached by the facts they use,
so the model is called again only when the data changes. A daily budget (`LLM_DAILY_CALLS`, default 150) caps calls because cloud tiers have limits the app cannot query; agent rationale rephrasing is off unless `LLM_RATIONALES=true`. Everything else works without it.

**Reliability.** `/api/health` reports each component and data source (`/status` in the app).
The database is copied to `backend/data/backups` at each start (three kept) and restored
automatically if it cannot be opened; public data sources are retried before a failure is
recorded; expired cache entries are pruned; a missing or stale analysis is rebuilt after a
restart.

## Layout

```
backend/app
  main.py            app factory, lifespan, wiring
  config.py, db.py   settings, DuckDB schema and response cache
  providers/         the only code that calls external services (Upstox, NSE, RSS, Yahoo, FRED, Ollama)
  services/          auth, instruments, quotes, candles, live relay, market, news, research,
                     portfolio, planner, insights, assistant, source monitor
  agents/            firm, industry, macro, sentiment (pure functions of a research context)
  tools/             pure computations (candles, market hours, quotes, technicals, scoring, headlines,
                     portfolio construction, backtesting, objectives, research diffs)
  api/routes/        thin HTTP and WebSocket handlers
frontend/src
  app/               shell and routing
  components/        UI primitives, quote table, search, charts
  features/          dashboard, stock, markets, watchlist, research, portfolio, status
  lib/               API client, live socket client, formatting, types
  styles/tokens.css  design tokens (dark and light)
```

To regenerate the protobuf module after an upstream `.proto` change:

```bash
cd backend/app/providers/upstox_proto
../../../.venv/Scripts/python -m pip install grpcio-tools
../../../.venv/Scripts/python -m grpc_tools.protoc -I. --python_out=. MarketDataFeed.proto
```

Research and education only. Nothing in this application is investment advice.
