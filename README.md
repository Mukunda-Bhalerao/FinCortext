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
| Industry and peers | NSE NIFTY 500 constituent CSV | NSE industry per company; peers are the 12 most traded members of the same industry |
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

## Layout

```
backend/app
  main.py            app factory, lifespan, wiring
  config.py, db.py   settings, DuckDB schema and response cache
  providers/         the only code that calls external services (Upstox, NSE, RSS, Yahoo, FRED, Ollama)
  services/          auth, instruments, quotes, candles, live relay, market, news, research
  agents/            firm, industry, macro, sentiment (pure functions of a research context)
  tools/             pure computations (candles, market hours, quotes, technicals, scoring, headlines)
  api/routes/        thin HTTP and WebSocket handlers
frontend/src
  app/               shell and routing
  components/        UI primitives, quote table, search, charts
  features/          dashboard, stock, markets, watchlist, research, portfolio
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
