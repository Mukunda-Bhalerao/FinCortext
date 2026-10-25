# AGENT.md — Working conventions for FinCortext

Read `PLAN.md` first. This file defines how code in this repo is written. Follow it for every change.

## Project in one paragraph
FinCortext is a research platform for NSE-listed Indian equities. A FastAPI backend pulls live and historical market data (Upstox first), stores it in DuckDB, runs four analysis agents (Firm, Industry, Macro, Sentiment) and a Portfolio agent, and serves a React + TypeScript dashboard.

## Hard rules
1. **No fabricated data.** Never hardcode prices, metrics, news, scores or sample rows in code paths the UI can reach. If data is unavailable, return an explicit empty/unavailable state.
2. **No invented numbers from language models.** All figures come from tools in `backend/app/tools/`. A model may only phrase results it is given.
3. **Provider isolation.** Only files in `backend/app/providers/` may talk to external market-data APIs. Everything else uses the `MarketDataProvider` interface.
4. **Secrets stay in `.env`.** Never log, commit or send tokens to the frontend.
5. **Zero-cost default.** Do not add a paid dependency or service. Anything optional (LLM, extra feeds) must be off by default and degrade gracefully.
6. **No brand or tool names tied to the assistant** in code, comments, commit messages, file names or UI copy.
7. **Research, not advice.** UI copy must not promise returns or give personalised instructions to buy or sell.

## Backend conventions
- Python 3.11+, FastAPI, Pydantic v2, DuckDB. Type hints everywhere.
- Async I/O for network calls (`httpx.AsyncClient`).
- Routes are thin. Logic lives in `services/`; pure computations live in `tools/` and must be unit-testable without network.
- Every provider call: timeout, retry with backoff, structured error mapped to an app error type.
- Cache provider responses in DuckDB with a TTL. Record `source` and `as_of` for every stored datapoint.
- Agent output must validate against `AgentOutput` (see `PLAN.md`). Include `evidence` and `data_gaps`.
- Candle timestamps: store UTC, convert to IST only at the edge.
- Format with `ruff`, test with `pytest`.

## Frontend conventions
- React + TypeScript (strict), Vite, TanStack Query, Tailwind with design tokens in `src/styles/tokens.css`.
- Charts: `lightweight-charts` for price/volume; keep chart code inside `components/charts/`.
- All colors, spacing and type sizes come from tokens. No ad-hoc hex values in components.
- Numbers: tabular figures, Indian grouping (`1,23,456.78`), ₹ symbol, consistent decimals per field type via `lib/format.ts`.
- Every data component implements loading, empty, error and stale states.
- No emojis, no placeholder text, no decorative gradients.
- Developer-facing detail (raw JSON, traces) belongs in the "Sources & data quality" drawer only.

## UI quality bar
- Dense, scannable, desktop-first, usable on mobile.
- Green/red only for price direction. One accent color elsewhere.
- Show "as of" times and market status wherever data is shown.
- Explanations appear as compact evidence chips that expand; avoid paragraphs of prose.

## Working method
- Build one vertical slice end to end before widening.
- Make small, reviewable changes. Prefer editing over regenerating whole files.
- When an external API's behavior is uncertain, check its documentation and say what was verified.
- After each change, state: what changed, how to run it, how to verify it.

## Commands (update as the repo grows)
```
# backend (uv sync also works)
cd backend && python -m venv .venv && .venv/Scripts/python -m pip install -e ".[dev]"
.venv/Scripts/python -m uvicorn app.main:app --reload --port 8000
.venv/Scripts/python -m pytest -q && .venv/Scripts/python -m ruff check app

# frontend
cd frontend && npm install && npm run dev
npm test && npm run build

# both
./dev.ps1
```
