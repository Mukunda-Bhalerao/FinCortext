# FinCortext — Data Sources

## Source priority principles

1. **Official filings are the primary source of truth for fundamentals.**
   Ingested CSV/XBRL/XML documents (legitimately obtained) take precedence.
2. **Upstox is the only market-data source** (search, quotes, historical
   candles, gauge candles). The Firm Agent never depends on a provider directly.
3. **No prohibited scraping.** No automated collection against NSE or other
   sources where automated access is prohibited or unsupported.
4. **Fail clearly, never fabricate.** Unavailable sources produce explicit
   statuses (LIVE / CACHED / IMPORTED_OFFICIAL / SAMPLE / UNAVAILABLE / ERROR).

## Implemented sources

### Market data — Upstox (`MarketDataProvider` adapter)
- Adapter: `backend/app/data/providers/market/upstox_provider.py` +
  `backend/app/data/providers/market/upstox_client.py`
- Instrument search V2 (`/v2/instruments/search`, NSE-EQ filter), Full Market
  Quotes V3 (`/v3/market-quote/quotes`), Historical Candle V3
  (`/v3/historical-candle/{key}/days/1/{to}/{from}`)
- Any valid NSE equity resolves dynamically (`instrument_key` canonical);
  daily OHLCV, configurable date ranges, normalized to canonical `MarketPrice`
- All failures raise `ProviderError`/`ProviderUnavailableError` (never silent
  gaps); no fallback provider exists
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

### Provider fundamentals — seam unwired (fallback/enrichment)
- Contract: `FundamentalDataProvider` (`app/domain/contracts/providers.py`);
  orchestration: `FundamentalsService`
  (`POST /api/fundamentals/refresh[/{symbol}]`, `GET /api/fundamentals/{symbol}`).
- **No provider is wired in production** after the Upstox consolidation:
  refreshes raise `ProviderUnavailableError` and the preparation flow degrades
  to stored observations honestly.
- Stored pre-consolidation observations (relabeled `legacy_import`) remain
  usable: annual income-statement + balance-sheet rows mapped to canonical
  metrics (`total_revenue`, `net_income`, `total_assets`, `total_equity`,
  `total_debt`); snapshot P/E + ROE ratios. The Firm Agent reads the shared
  repository generically and does not depend on any provider; official
  filings stay primary wherever present.
- **Point-in-time honesty:** annual values carry real fiscal `period_end`
  dates; snapshot ratios carry no statement period, so their `available_at`
  falls back to ingestion time (stated as a limitation on every refresh).
  When a provider IS wired (tests/future), refresh replaces the previous
  provider snapshot per symbol (scoped delete by `provider` source type);
  official filing observations are never touched.
- No website scraping involved anywhere. No fabricated values.

### News — Google News RSS, NewsAPI optional (`NewsProvider` adapters)
- Primary adapter: `backend/app/data/providers/news/googlenews_rss.py`
  (`GoogleNewsRssProvider`) — free, keyless Google News RSS search
  (`hl=en-IN&gl=IN&ceid=IN:en`) with company-name query variants (short name
  → full legal name → symbol + "NSE", stopping at the first variant with
  ≥ 5 items), plus a Yahoo Finance headlines RSS fallback inside the same
  provider. Only feed XML is fetched and parsed (stdlib ElementTree) — no
  article-page scraping. Browser User-Agent, 10s timeout, ≤1 request/sec,
  2 retries with backoff, 6h per-query cache. `NEWS_PROVIDER=google_rss`
  (default) or `newsapi`.
- Secondary adapter: `NewsAPINewsProvider` (NewsAPI) — API key loaded only
  from `NEWS_API_KEY` env var (never committed). Attached as the merge source
  whenever configured: both feeds are fetched and merged, storage dedups by
  `article_id`.
- Article dedup via content hash; source metadata preserved (Google's
  " - Source" title suffix is split into the source field; HTML stripped
  from snippets).

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
- Macro series for gauges Upstox cannot serve (FX spot, global commodities/rates)

Each will be added as a new adapter implementing the existing provider
interfaces — no agent changes required.