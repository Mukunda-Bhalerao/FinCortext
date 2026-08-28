# FinCortext — Data Sources

## Source priority principles

1. **Official filings are the primary source of truth for fundamentals.**
   Ingested CSV/XBRL/XML documents (legitimately obtained) take precedence.
2. **yfinance is a development/fallback/enrichment source** for market data and
   optional fundamental enrichment. The Firm Agent never depends on it directly.
3. **No prohibited scraping.** No automated collection against NSE or other
   sources where automated access is prohibited or unsupported.
4. **Fail clearly, never fabricate.** Unavailable sources produce explicit
   statuses (LIVE / CACHED / IMPORTED_OFFICIAL / SAMPLE / UNAVAILABLE / ERROR).

## Implemented sources

### Market data — yfinance (`MarketDataProvider` adapter)
- Adapter: `backend/app/data/providers/market/yfinance_provider.py`
- NSE tickers via universe config (`RELIANCE` → `RELIANCE.NS`)
- Daily OHLCV, configurable date ranges, normalized to canonical `MarketPrice`
- All failures raise `ProviderError` (never silent gaps)
- Replaceable: implement `MarketDataProvider` with any licensed feed

### Official filings — file ingestion (primary for fundamentals)
- Service: `backend/app/services/filing_service.py`
- Formats (priority order):
  1. **XBRL/XML** — structured facts, contextRef periods, unit resolution
  2. **CSV** — structured exports (schema: `data/sample/sample_filing.csv`)
  3. **PDF** — **limited fallback**: pypdf text extraction + conservative
     label/value line matching. Arbitrary annual reports cannot be reliably
     parsed; results carry explicit quality warnings.
- Every ingestion preserves: entity, metric, value, unit, currency, period,
  statement type, consolidation basis, filing/published/available timestamps,
  source metadata, raw document reference, content hash, schema version.
- Duplicate detection via SHA-256 content hash.
- Raw files archived under `data/raw/filings/`.

### News — NewsAPI (`NewsProvider` adapter)
- Adapter: `backend/app/data/providers/news/` (Milestone 7)
- API key loaded only from `NEWS_API_KEY` env var (never committed)
- Article dedup via content hash; source metadata preserved
- Replaceable: future RSS, GDELT, licensed providers implement `NewsProvider`

### Sentiment — local FinBERT (no paid API)
- Model: `ProsusAI/finbert` via Hugging Face transformers (configurable)
- Runs locally; downloads once to `FINCORTEXT_SENTIMENT_CACHE_DIR`
- Unavailable model → explicit degraded status, never fabricated scores

## Sample / demo data

`data/sample/` contains clearly-labeled fixtures (`sample_filing.csv`,
`sample_filing.xbrl`) used by tests and for explicit demo selection in the UI.
Sample data is NEVER silently substituted for live data — status always
travels with the data.

## Future sources (architecture seams only)

- Licensed fundamentals (Bloomberg/Refinitiv/official exchanges where permitted)
- RSS/GDELT news, industry report documents
- Macro series (for the future Macro Analyst)

Each will be added as a new adapter implementing the existing provider
interfaces — no agent changes required.