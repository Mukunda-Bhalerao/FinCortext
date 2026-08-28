# FinCortext

**AI-Powered Investment Intelligence and Agentic Portfolio Management Platform**

FinCortext is a research-oriented financial intelligence platform. It ingests market,
official-filing and news data through replaceable provider adapters, normalizes it into
canonical domain data, and runs deterministic, explainable analyst agents whose
standardized outputs are designed to be consumed by a future Portfolio Agent.

---

## 1. Current implementation scope (V1)

**Implemented (real working logic):**

- Foundation layer: configuration, logging, error handling, health endpoint
- Canonical domain models + standardized `AgentOutput` contract
- DuckDB analytical storage with provenance and point-in-time metadata
- Versioned stock universe (10 Indian NSE large-caps)
- Market data pipeline: yfinance adapter → validation → normalization → DuckDB → API
- Official filing ingestion: CSV / XBRL / XML parsers + limited PDF fallback, with
  full provenance and point-in-time (`period_end` vs `available_at`) metadata
- **Firm Analyst** — deterministic fundamental/valuation/momentum scoring
- **Industry Analyst** — peer-group and sector-relative deterministic scoring
- **News + Sentiment pipeline** — NewsAPI provider, local FinBERT sentiment model,
  deterministic time-aware aggregation
- React + TypeScript dashboard frontend with explicit data-status labels
  (LIVE / CACHED / IMPORTED OFFICIAL / SAMPLE / UNAVAILABLE / ERROR)

**NOT implemented (explicit placeholders only):**

- Macro Analyst
- Portfolio Agent / orchestration
- Risk & constraint engine, portfolio optimization
- Backtesting, performance evaluation, scenario/stress testing
- Explainability module beyond per-agent rationale/evidence
- Authentication, deployment infrastructure, licensed data providers

## 2. Architecture overview

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
API (FastAPI)  →  Frontend (React + TS)   …   future Portfolio Agent
```

Agents never call external providers directly; they consume canonical domain data
through repositories/services.

## 3. Repository structure

```
fincortext/
├── frontend/          React + TypeScript + Vite dashboard
├── backend/           FastAPI application (app/) + tests/
├── data/              raw/ filings & fixtures, processed/ (DuckDB), sample/
├── docs/              data model, agent contracts, data sources, notes
├── scripts/           helper scripts
├── ARCHITECTURE.md    module boundaries and data flow
├── PROGRESS.md        milestone status — read this to continue development
└── README.md
```

## 4. Technology stack

| Layer     | Technology |
|-----------|------------|
| Frontend  | React 18, TypeScript, Vite, Recharts |
| Backend   | Python 3.11+, FastAPI, Pydantic |
| Storage   | DuckDB (local analytical DB), Parquet/CSV for raw artifacts |
| Market    | yfinance (behind a replaceable provider interface) |
| News      | NewsAPI (behind a replaceable provider interface) |
| Sentiment | Hugging Face transformers (FinBERT — local, no paid API) |
| Testing   | pytest (backend), Vitest (frontend) |

## 5. Prerequisites

- Python 3.11+
- Node.js 18+ (tested with Node 24)
- npm

## 6. Environment setup

```bash
# 1. Backend dependencies
pip install -r backend/requirements.txt

# 2. Frontend dependencies
cd frontend && npm install
```

Create your environment file:

```bash
cp .env.example .env
```

## 7. Configuring NEWS_API_KEY

1. Get a free key at https://newsapi.org
2. Put it in `.env` (never commit this file):

```
NEWS_API_KEY=your-key-here
```

If the key is absent the backend still starts; the Sentiment Analyst reports
news retrieval as **UNAVAILABLE** and can use explicitly selected sample data.

Other useful settings (see `.env.example`): `FINCORTEXT_DB_PATH`,
`FINCORTEXT_PORT`, `FINCORTEXT_LOG_LEVEL`, `FINCORTEXT_SENTIMENT_MODEL`.

## 8. Running the backend

```bash
cd backend
python -m uvicorn app.main:app --reload --port 8000
```

- Health check: http://127.0.0.1:8000/health
- API docs: http://127.0.0.1:8000/docs

## 9. Running the frontend

```bash
cd frontend
npm run dev
```

Open http://localhost:5173 (API calls are proxied to the backend).

## 10. Ingesting official financial files

Use the **Data → Filing Import** page in the UI, or POST the file directly:

```bash
curl -X POST http://127.0.0.1:8000/api/filings/import \
  -F "file=@data/raw/filings/reliance_annual.csv" \
  -F "symbol=RELIANCE" \
  -F "source_name=Company Annual Report FY2024"
```

Supported formats (priority order):

1. **XBRL/XML** — structured financial facts (best quality)
2. **CSV** — structured exports (see `data/sample/sample_filing.csv` for the schema)
3. **PDF** — *limited fallback*: basic text extraction only. Arbitrary PDF annual
   reports cannot be reliably parsed; the system reports extraction quality
   limitations explicitly rather than inventing data.

Every ingestion preserves provenance: source name/type, filing date, content hash,
ingestion timestamp, and the point-in-time distinction between the financial
period end and when the information became publicly available.

## 11. Retrieving market and news data

```bash
# Refresh market prices for the whole universe (yfinance)
curl -X POST http://127.0.0.1:8000/api/market/refresh

# Refresh prices for one symbol
curl -X POST http://127.0.0.1:8000/api/market/refresh/TCS

# Stored price series with explicit LIVE/CACHED/UNAVAILABLE status
curl http://127.0.0.1:8000/api/market/prices/TCS

# News provider configuration status
curl http://127.0.0.1:8000/api/news/status

# Fetch live news for one company (requires NEWS_API_KEY; graceful
# UNAVAILABLE response when the key is missing — never an error/crash)
curl -X POST http://127.0.0.1:8000/api/news/refresh/TCS

# Stored (cached) articles for a company
curl http://127.0.0.1:8000/api/news/TCS
```

## 12. Running the agents

```bash
curl -X POST http://127.0.0.1:8000/api/agents/firm/RELIANCE/run
curl -X POST http://127.0.0.1:8000/api/agents/industry/RELIANCE/run
curl -X POST http://127.0.0.1:8000/api/agents/sentiment/RELIANCE/run
```

Each returns the standardized `AgentOutput` contract (score, signal, confidence,
factors, rationale, evidence, limitations). Outputs are persisted and can be
listed via `GET /api/agents/outputs?agent_id=firm_analyst&symbol=RELIANCE`.

Methodology documentation (weights, formulas, confidence rules, determinism):

- Firm Analyst: `backend/app/agents/firm/methodology.py`
- Industry Analyst: [docs/industry_methodology.md](docs/industry_methodology.md)
- Sentiment Analyst: [docs/sentiment_methodology.md](docs/sentiment_methodology.md)

The **Intelligence → Combined Summary** page runs all three analysts for one
company and shows their scores together. Portfolio synthesis is explicitly
reserved for the future Portfolio Agent — no recommendations or weights are
generated.

## 13. Running tests

```bash
# Backend (unit + integration; add -m network for live-provider tests)
cd backend && python -m pytest

# Frontend
cd frontend && npm test
```

## 14. Current limitations

- PDF filing parsing is a basic extraction fallback, not a reliable parser for
  arbitrary annual reports.
- yfinance/NewsAPI are unofficial/free services: rate limits and outages happen;
  all failures are surfaced as explicit provider errors, never silent gaps.
- The FinBERT model downloads on first use (~440 MB) and needs internet once;
  without it the Sentiment Analyst reports degraded status.
- Universe metadata (sector/industry) is configuration, not verified against a
  licensed classification provider.
- Single-user local research tool: no auth, no multi-tenancy.

## 15. Not implemented yet

Macro Analyst, Portfolio Agent, risk/constraint engine, optimization, backtesting,
performance evaluation, scenario/stress testing, explainability module, alerts,
authentication/deployment, licensed data providers. These exist only as explicit
"Coming soon" UI placeholders and architecture seams.

## 16. Continuing development

Read **[PROGRESS.md](PROGRESS.md)** — it records completed milestones, current
state, test status, known limitations, and the exact next recommended milestone.
Then read [ARCHITECTURE.md](ARCHITECTURE.md) and [docs/agent_contracts.md](docs/agent_contracts.md).