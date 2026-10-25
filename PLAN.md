# FinCortext — Project Plan

AI-assisted investment research platform for Indian equities (NSE). Live market data, fundamentals, industry/peer analysis, news sentiment and macro context, combined by four analysis agents into explainable portfolio construction.

**Constraints**
- Zero recurring spend. Free data sources and free/local models only.
- No hardcoded or placeholder outputs. Every figure shown comes from a provider or a computation.
- Professional product feel: dense, data-first UI. No developer-facing noise on screen.
- Research and education tool. Never promise returns or present predictions as facts.

---

## 1. Principles

1. **Providers are swappable.** All market data flows through a `MarketDataProvider` interface. Upstox is the first implementation; Angel One, Dhan or `yfinance` can be added without touching other code.
2. **Compute is deterministic, language is optional.** Numbers come from Python tools (pandas/numpy). A language model, when used, only writes the rationale from tool results. It may never introduce a number.
3. **Every claim carries evidence.** Agent outputs include `evidence[]` (metric, value, source, as-of time) and `data_gaps[]`.
4. **Degrade honestly.** If data is missing or the market is closed, say so in the UI with an "as of" timestamp.
5. **Cache everything.** Free APIs are rate-limited. Persist to DuckDB, refresh on schedules.

---

## 2. Architecture (maps to the system diagram)

| Diagram layer | Implementation |
|---|---|
| 1. Data sources | Upstox (prices, candles, instruments), `yfinance` (fundamentals fallback), RSS (news), RBI/MOSPI/FRED (macro) |
| 2. Data pipeline | `jobs/` (APScheduler): ingest → validate → normalize → features → DuckDB |
| 3. Agent layer | `agents/`: Firm, Industry, Macro, Sentiment. Each is a module with tools and a strict output schema |
| 4. Portfolio layer | Portfolio Agent, constraint engine, optimizer (PyPortfolioOpt) |
| 5. Execution & backtesting | Walk-forward backtester (Phase 3) |
| 6. Outputs | React dashboard, stock pages, portfolio view, AI explanations |
| 0. Foundation | Config, logging, versioned prompts/schemas, data lineage table, human review flags |

### What "agent" means here

An agent is a **role-bound module** that (a) decides which data it needs, (b) gathers it through tools, (c) computes metrics, and (d) returns a structured verdict. It does not need to be an LLM.

| Agent | Phase 1 (free, deterministic) | Phase 2 (optional language layer) |
|---|---|---|
| Firm | Ratios, growth, margins, valuation vs peers, technicals via pandas | Plain-English summary from computed results |
| Industry | Sector index returns, peer percentile ranks, constituent breadth | Narrative on sector position |
| Macro | Rates, inflation, FX, FII/DII flows, sector sensitivity table | Short macro brief |
| Sentiment | RSS headlines scored by a local FinBERT model | Theme summary |
| Portfolio | Combines scores, applies constraints, runs optimizer | Rationale per holding |

LLM options at zero cost: Gemini or Groq free tier, or a local model via Ollama. Wrap behind `LLMClient`. If no model is configured, the UI uses templated text built from the evidence list, so the product still works.

### Agent output contract

```python
class AgentOutput(BaseModel):
    agent: Literal["firm", "industry", "macro", "sentiment"]
    subject: str                      # symbol or sector
    signal: Literal["positive", "neutral", "negative", "insufficient_data"]
    score: float                      # -1.0 .. 1.0
    confidence: float                 # 0.0 .. 1.0
    evidence: list[Evidence]          # metric, value, unit, source, as_of
    data_gaps: list[str]
    rationale: str | None             # optional, generated from evidence only
    computed_at: datetime
```

---

## 3. Data sources

| Need | Source | Notes |
|---|---|---|
| Live quotes | Upstox market quote / market data feed | Requires a valid access token |
| Candles (1m … 1M) | Upstox historical + intraday candle V3 | See section 4 |
| Instrument master | Upstox instrument file | Source of truth for instrument keys; never guess ISINs |
| Fundamentals | `yfinance` (`SYMBOL.NS`) first | Unofficial; cache and expect gaps. Add filings later |
| Index data, movers | Compute from the Nifty 50/100/500 universe using batch quotes | Verify whether Upstox exposes a movers endpoint before building your own |
| FII/DII, delivery data | NSE public endpoints via a wrapper | Fragile; cache and fail soft |
| News | RSS (ET, Moneycontrol, Business Standard, Google News) | Store headline, link, time, source only |
| Macro | RBI, MOSPI, FRED | Daily/weekly refresh |

Scraping policy: prefer APIs and RSS. Respect each site's terms and `robots.txt`, throttle requests, cache results, and never scrape pages behind logins.

---

## 4. Upstox integration

**Auth.** Standard OAuth: login dialog → redirect with `code` → exchange for access token. Store the token server-side only (never in the frontend). Tokens expire daily, so the backend needs a visible "Reconnect Upstox" state. Check the developer portal for whether a long-lived read-only token is available for your app type.

**Candles (V3).** `GET /v3/historical-candle/{instrument_key}/{unit}/{interval}/{to_date}/{from_date}` and `GET /v3/historical-candle/intraday/{instrument_key}/{unit}/{interval}`.

- Units: minutes (1–300), hours (1–5), days (1), weeks, months.
- Minute data starts January 2022. Requests for 1–15 minute intervals cover at most 1 month per call; larger minute intervals at most 1 quarter. Day and month history goes back to 2000.
- Intraday endpoint returns the current session. Historical endpoint returns completed days. Merge both for a continuous chart.

**Timeframe selector → request mapping**

| UI | unit | interval | range loaded |
|---|---|---|---|
| 1m | minutes | 1 | today + last few sessions |
| 5m | minutes | 5 | 1 month |
| 15m | minutes | 15 | 1 month |
| 1H | hours | 1 | 1 quarter |
| 1D | days | 1 | 1–5 years |
| 1W | weeks | 1 | 5+ years |
| 1M | months | 1 | max |

**Live prices.**
- Phase 0: backend polls the batch quote endpoint every 2–3 seconds for symbols currently on screen and pushes updates to the frontend over a WebSocket.
- Phase 1: switch to Upstox's market data WebSocket (protobuf), subscribe only to visible symbols, relay through the same frontend socket. The frontend never changes.

**Known pitfall.** Instrument keys use ISINs (`NSE_EQ|INE...`). A wrong ISIN returns an empty candle list without an error. Always resolve keys from the instrument master.

**Market hours.** NSE equity session is 09:15–15:30 IST, Monday–Friday. Outside it, show last close and label it.

---

## 5. Repository layout

```
fincortext/
├── AGENT.md                  # conventions for any coding assistant
├── PLAN.md
├── .env.example
├── backend/
│   ├── pyproject.toml
│   └── app/
│       ├── main.py
│       ├── config.py
│       ├── api/routes/       # auth, market, stocks, news, portfolio, ws
│       ├── providers/        # base.py, upstox.py, yfinance_provider.py
│       ├── services/         # quotes, candles, instruments, movers
│       ├── agents/           # base.py, firm.py, industry.py, macro.py, sentiment.py, portfolio.py
│       ├── tools/            # pure functions: ratios, technicals, peers, risk
│       ├── schemas/          # pydantic models (API + agent outputs)
│       ├── db/               # duckdb connection, migrations
│       ├── jobs/             # scheduled ingestion
│       └── llm/              # LLMClient + providers (optional)
└── frontend/
    ├── package.json
    └── src/
        ├── app/              # shell, routing, providers
        ├── components/       # ui primitives, data table, chart wrappers
        ├── features/
        │   ├── dashboard/
        │   ├── stock/
        │   └── portfolio/
        ├── lib/              # api client, ws client, formatters
        └── styles/           # tokens.css
```

### `.env.example`

```
UPSTOX_API_KEY=
UPSTOX_API_SECRET=
UPSTOX_REDIRECT_URI=http://localhost:8000/api/auth/upstox/callback
# Optional: paste a token manually while developing
UPSTOX_ACCESS_TOKEN=

# Optional language layer (leave empty to use templated text)
LLM_PROVIDER=none
GEMINI_API_KEY=
GROQ_API_KEY=

DUCKDB_PATH=./data/fincortext.duckdb
```

---

## 6. UI direction

- **Reference density:** Kite, Groww Pro, Koyfin, Screener. Left navigation, index strip on top, dense tables, tabular numerals.
- **Palette:** neutral grays, one accent. Green/red reserved for price change. Dark and light themes via CSS variables.
- **Typography:** one UI sans (Inter or Geist) plus a mono/tabular style for figures.
- **Explainability:** inline evidence chips (`P/E 24.1 · sector median 29.8 · Yahoo · 25 Oct`) that expand on click. No essays on screen.
- **Machinery hidden:** logs, raw JSON and agent traces live in a "Sources & data quality" drawer.
- **States:** skeleton loaders, empty states, error states, stale-data badges, "Market closed" labels.
- **Never on screen:** emojis, placeholder lorem text, mock numbers, "AI-generated" captions.

### Dashboard (home)
Index strip (Nifty 50, Sensex, Bank Nifty, Nifty IT, India VIX) · watchlist · top gainers/losers/most active · sector heatmap · market news with sentiment tag · market status.

### Stock page
Header (name, symbol, price, change, day range, 52w range) · candlestick chart with volume and timeframe selector · key metrics grid · peers table · industry panel · agent verdict cards with expandable evidence.

### Portfolio
Holdings table · allocation by stock/sector · risk metrics (volatility, Sharpe, max drawdown, beta vs Nifty 50) · model portfolio generator with constraints · performance vs benchmark.

---

## 7. Roadmap

### Phase 0 — Foundation + live dashboard (tonight)
- [ ] Repo scaffold, env handling, FastAPI app, health route
- [ ] Upstox OAuth flow and token storage
- [ ] Instrument master loader into DuckDB, symbol search
- [ ] Quote service and candle service (all 7 timeframes)
- [ ] WebSocket relay (polling first)
- [ ] Frontend shell, theme tokens, index strip, watchlist, movers
- [ ] Stock page with candlestick chart, volume, timeframe selector, live tick

**Done when:** you can open the dashboard, search any NSE stock, open it, switch between 1m/5m/15m/1H/1D/1W/1M, and see the last candle update live during market hours.

### Phase 1 — Research data
- [ ] Fundamentals ingestion, peer mapping, sector index returns
- [ ] RSS ingestion and FinBERT sentiment
- [ ] Stock page metrics, peers, industry panel (real data)
- [ ] Firm and Industry agents with evidence output

### Phase 2 — Agents and portfolio
- [ ] Sentiment and Macro agents
- [ ] Portfolio Agent: score aggregation, constraints, optimizer
- [ ] Holdings input, risk metrics, benchmark comparison
- [ ] Optional LLM rationale layer

### Phase 3 — Evaluation
- [ ] Walk-forward backtester with costs and slippage
- [ ] Performance attribution, stress scenarios
- [ ] Alerts, reports, human review flags

---

## 8. Risks

| Risk | Mitigation |
|---|---|
| Daily token expiry | Visible reconnect state, background refresh checks |
| Free API gaps or breakage | Provider interface, cached fallbacks, `data_gaps[]` in outputs |
| Rate limits | Subscribe only to visible symbols, batch requests, cache |
| Fundamentals quality | Show source and as-of date; flag missing fields rather than estimate |
| Regulatory (SEBI adviser rules) | Research/education framing, no personalised buy/sell instructions, no return promises |
| Data redistribution licensing | Personal use only until a licensed feed is in place |

---

## 9. Definition of professional

- Every number traceable to a source and timestamp.
- No screen shows data it did not fetch.
- Errors are explained in user language; developer detail is in logs.
- Typed end to end (Pydantic on the backend, TypeScript on the frontend).
- One command starts backend and frontend.
