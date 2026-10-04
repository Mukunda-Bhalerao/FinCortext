# FinCortext — Data Model

## Overview

FinCortext separates **raw/source data** (filing documents, provenance events)
from **normalized canonical data** (market prices, financial observations, news
articles, sentiment results, agent outputs). All storage is DuckDB
(`FINCORTEXT_DB_PATH`, default `data/processed/fincortext.duckdb`).

## Tables

### `universe_metadata` — mirror of the versioned universe config
| column | type | notes |
|---|---|---|
| symbol | VARCHAR PK | internal symbol, e.g. `RELIANCE` |
| name | VARCHAR | company name |
| exchange | VARCHAR | e.g. `NSE` |
| ticker | VARCHAR | provider ticker, e.g. `RELIANCE.NS` |
| sector / industry | VARCHAR | classification metadata |
| universe_version | VARCHAR | config version used |

### `market_prices` — canonical OHLCV
| column | notes |
|---|---|
| symbol, trade_date | composite PK |
| open/high/low/close | positive floats |
| volume | ≥ 0 |
| currency | default `INR` |
| provider_ticker | e.g. `RELIANCE.NS` |
| source_type / source_name | provenance |
| ingested_at | ingestion timestamp |

### `financial_observations` — one metric value per row
| column | notes |
|---|---|
| observation_id | UUID PK |
| entity_id | internal symbol |
| metric | canonical key: `total_revenue`, `net_income`, `total_debt`, `total_equity`, `total_assets`, `operating_profit`, `eps`, … |
| value / unit / currency | numeric value with explicit unit (`INR`, `INR_lakh`, `INR_cr`, `ratio`, `percent`) |
| period_start / period_end | financial period covered |
| statement_type | income_statement / balance_sheet / cash_flow / other |
| consolidation_basis | standalone / consolidated / unknown |
| fiscal_year | e.g. `FY2024` |
| filing_date / published_at / available_at | **point-in-time metadata** — `available_at` is when the info became public; backtests must filter on it |
| content_hash / source_* / raw_document_reference | provenance |
| schema_version / ingested_at | reproducibility |

### `filing_documents` — raw layer metadata
document_id (PK, content-hash based), entity_id, document_type (`csv|xbrl|xml|pdf`),
file_name, file_path, content_hash, source_*, filing_date, published_at,
ingested_at, observation_count, parse_warnings.

### `news_articles` — canonical news
article_id (PK, content-hash based), entity_id, title, description, content,
source, source_url, published_at, collected_at, language, content_hash, source_*.

### `sentiment_results`
article_id + model_id (composite PK), entity_id, label
(`positive|neutral|negative`), positive/neutral/negative probabilities,
model_confidence, scored_at.

### `agent_outputs` — standardized AgentOutput persistence
output_id (PK), agent_id, entity_id, score (0–100), signal, confidence,
factors_json (full structured factors/rationale/evidence/limitations),
generated_at, data_version, status (`OK|DEGRADED|UNAVAILABLE`).

### `data_provenance` — ingestion event log
event_id (PK), event_type, entity_id, source_type, source_name, content_hash,
rows_ingested, rows_rejected, detail, ingested_at.

### `market_quotes` — live quote snapshots (one row per symbol, upsert)
symbol (PK), instrument_key, trading_symbol, exchange, segment, source,
timestamp (provider timestamp, never wall clock), OHLC + volume + 52-week
fields, day change, updated_at. Newer-wins; Upstox outranks legacy imports.

### `upstox_instruments` — instrument registry (dynamic equity metadata cache)
instrument_key (PK), symbol, trading_symbol, name, exchange, segment, isin,
exchange_token, instrument_type, updated_at.

### `research_reports` — web-research evidence (Gemini grounding, labeled)
report_id (PK), entity_id, report_type (`company_profile` | `peer_discovery` |
`news_digest`), subject, payload_json, confidence, sources_json, model,
source_name, created_at. Evidence ONLY — never market data, never articles,
never scored. Upserted per entity+type+subject (no duplicates on repeat
preparation).

## Canonical metric keys (initial set)

`total_revenue`, `revenue_growth`, `net_income`, `operating_profit`,
`total_assets`, `total_equity`, `total_debt`, `eps`, `roe`, `roce`,
`pe_ratio`, `operating_margin`, `net_margin`.

Units are explicit per observation; ratio/percent metrics use `ratio`/`percent`
units rather than currency.

## Point-in-time rules

1. `period_end` = end of the financial period the value describes.
2. `available_at` = earliest time the value was publicly knowable
   (published_at → filing_date → ingested_at fallback chain).
3. All agent/backtest reads use `available_at <= as_of` filtering
   (`FinancialRepository.get_observations(as_of=...)`).