# FinCortext — Architecture

## 1. Design goals

1. **Source-agnostic agents.** Analyst agents consume canonical FinCortext domain
   data through repositories/services — never external providers or websites.
2. **Replaceable providers.** Every external data source (yfinance, NewsAPI,
   future licensed feeds) sits behind a narrow provider interface.
3. **Deterministic, explainable intelligence.** Agent scores are computed by
   documented, testable formulas — no random numbers, no LLM-invented conclusions.
4. **Provenance and point-in-time correctness.** Every stored observation records
   where it came from and when it became available, so future backtests can
   distinguish *financial period end* from *public availability*.
5. **Honest degradation.** Missing keys, provider outages, or unavailable models
   produce explicit statuses (LIVE / CACHED / IMPORTED OFFICIAL / SAMPLE /
   UNAVAILABLE / ERROR) — never silently substituted data.

## 2. Module boundaries

```
backend/app/
├── core/          config, logging, exceptions (no business logic)
├── domain/
│   ├── models/    canonical Pydantic domain models
│   └── contracts/ provider interfaces + AgentOutput contract
├── data/
│   ├── providers/    adapters: market/ (yfinance), fundamentals/, news/ (NewsAPI)
│   ├── ingestion/    file import: filings (CSV/XBRL/XML/PDF-limited)
│   ├── validation/   schema + sanity validation per data type
│   ├── normalization/ raw → canonical mapping
│   ├── storage/      DuckDB connection + schema
│   └── universe/     versioned stock universe configuration
├── repositories/  typed read/write access to DuckDB (agents use these)
├── agents/
│   ├── base/       shared agent interface + AgentOutput builder
│   ├── firm/       Firm Analyst (deterministic)
│   ├── industry/   Industry Analyst (deterministic)
│   └── sentiment/  Sentiment Analyst (local FinBERT + deterministic aggregation)
├── services/      orchestration used by API routes (no logic in routes)
└── api/routes/    thin FastAPI route modules by domain
```

**Rule:** route handlers only parse requests, call services, and shape responses.
Business logic lives in services/agents/repositories.

## 3. Data flow

```
┌──────────────────────────── DATA SOURCES ───────────────────────────┐
│ yfinance (market)   NewsAPI (news)   Official filings (CSV/XBRL/PDF) │
│ Future: licensed fundamentals, RSS/GDELT, industry reports           │
└──────────────────────────────┬──────────────────────────────────────┘
                               ↓ provider adapters / file import
┌──────────────────────────── DATA PIPELINE ──────────────────────────┐
│ ingestion → validation → normalization → feature/metric calculation  │
└──────────────────────────────┬──────────────────────────────────────┘
                               ↓
┌──────────────────────── DUCKDB STORAGE ─────────────────────────────┐
│ market_prices · universe_metadata · financial_observations ·         │
│ filing_documents · news_articles · sentiment_results ·               │
│ agent_outputs · data_provenance                                      │
└──────────────────────────────┬──────────────────────────────────────┘
                               ↓ repositories (source-agnostic reads)
┌──────────────────────────── AGENT LAYER ────────────────────────────┐
│ Firm Analyst    Industry Analyst    Sentiment Analyst                │
│ (Macro Analyst + Portfolio Agent: future, consume same contract)     │
└──────────────────────────────┬──────────────────────────────────────┘
                               ↓ standardized AgentOutput
                    FastAPI services/routes → React frontend
                    (future Portfolio Agent consumes AgentOutputs)
```

## 4. Provider abstraction

Conceptual interfaces (see `app/domain/contracts/providers.py`):

- `MarketDataProvider` — `fetch_ohlcv(ticker, start, end) -> list[MarketPrice]`
- `FundamentalDataProvider` — development/fallback enrichment only; ingested
  official filings are the primary source of truth for fundamentals.
- `NewsProvider` — `fetch_articles(query, from, to) -> list[NewsArticle]`

Adapters translate provider-specific quirks (NSE `.NS` suffixes, NewsAPI payload
shapes) into canonical domain models **at the boundary**. Agents never see
provider payloads.

## 5. Storage

DuckDB (single local file, configured via `FINCORTEXT_DB_PATH`) holds both raw
provenance records and normalized canonical tables. Raw/source concepts (filing
documents, provider fetch metadata) are kept separate from normalized data
(market prices, financial observations, news articles). See
[docs/data_model.md](docs/data_model.md) for the physical schema.

## 6. Canonical data contracts

All pipeline stages exchange Pydantic models from `app/domain/models`:
`MarketPrice`, `FinancialObservation`, `NewsArticle`, `SentimentResult`,
`AgentOutput`, plus provenance metadata. Contracts are documented in
[docs/agent_contracts.md](docs/agent_contracts.md) and
[docs/data_model.md](docs/data_model.md).

## 7. Agent architecture

Each agent:

1. Pulls canonical data via repositories (never providers).
2. Computes deterministic factors with documented formulas and weights.
3. Handles missing data by reducing evidence and confidence — never fabricating.
4. Emits the standardized `AgentOutput` (score 0–100, signal, confidence,
   factors, rationale, evidence, limitations, provenance references).
5. Persists its output for history and future Portfolio Agent consumption.

The future Portfolio Agent will consume `AgentOutput`s from all analysts
through the same contract — no hidden agent-to-agent coupling.

## 8. Future Portfolio Agent integration

Reserved seams (no fake implementations):

- `AgentOutput` contract is already portfolio-ready (entity-scoped, scored,
  confidence-weighted, provenance-linked).
- Universe configuration provides the tradable set.
- Storage schema leaves room for portfolio/optimization tables.
- Frontend Portfolio/Research pages are explicit "Coming soon" placeholders.