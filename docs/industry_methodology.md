# Industry Analyst — Methodology

> Implementation: `backend/app/agents/industry/methodology.py` and
> `backend/app/agents/industry/industry_agent.py`
> Version: `industry_analyst_v1` (recorded in every output's `provenance`)

## Purpose

The Industry Analyst answers a **different question from the Firm Analyst**:

> "How attractive is the company's sector environment, and how does the
> company compare against its relevant peers?"

It measures the *environment* (peer momentum, volatility regime) and the
company's *relative position* (relative strength, margin vs peer median) —
not absolute company quality.

## Data sources (canonical, via repositories only)

| input | source | used for |
|---|---|---|
| Universe config | `app/data/universe/universe_config.py` (versioned) | peer grouping |
| Stored OHLCV prices | `MarketRepository` (DuckDB) | momentum, volatility |
| Ingested filing observations | `FinancialRepository` (DuckDB) | net margins |

The agent **never** calls external providers and **never** fabricates data.

## Peer group construction

1. Start from the universe entry for the target symbol. For dynamically
   searched stocks, the entry is classified first (`IndustryClassifier`:
   static universe → official NSE Nifty 500 list →
   Gemini research last resort → honest "Unknown").
2. Peers = universe entries sharing the same `sector`
   (falling back to `industry` grouping when the sector has fewer than
   3 members — see `get_sector_peers`).
3. When configured peers are insufficient, preparation discovers more in
   relevance order: curated same-sector candidates, then other symbols from
   the NSE Nifty 500 list sharing the company's industry (cap 8, self
   excluded), then Gemini-suggested candidates. Every candidate must resolve
   live via Upstox (exact listing) AND hold real price history
   (`ensure_history`) before it counts — failures are skipped, never invented.
4. **The target company itself is always excluded** from peer medians
   (`[p for p in get_sector_peers(entity) if p.symbol != entity]`).
5. Peer statistics use the **median** (robust to outliers), never the mean.

Factors, weights, and scoring maps are unchanged by peer discovery.

## Factors and weights (sum = 1.0)

| # | factor | weight | definition | scoring map (linear, capped 0–100) |
|---|---|---|---|---|
| 1 | `peer_momentum` | 0.30 | median 90-day momentum of peers with price history | −20% → 0 pts, +20% → 100 pts |
| 2 | `relative_strength` | 0.30 | company 90-day momentum − peer-median momentum | −10pp → 0 pts, +10pp → 100 pts |
| 3 | `peer_fundamentals` | 0.25 | company net margin − peer-median net margin (filings only) | −10pp → 0 pts, +10pp → 100 pts |
| 4 | `sector_volatility` | 0.15 | company annualized volatility ÷ peer-median volatility | 2.0× → 0 pts, 0.5× → 100 pts (lower vol is better) |

All mappings use the shared `linear_score(value, worst, best)` helper:
`(value − worst) / (best − worst) × 100`, clamped to [0, 100].

### Momentum window

- Window: **90 calendar days** back from the latest stored trade date
  (`MOMENTUM_WINDOW_DAYS = 90`).
- Base price = latest stored close on or before the cutoff date; if none
  exists, the earliest stored close is used.
- Momentum = `latest_close / base_close − 1` (simple return, not annualized).

### Volatility convention (documented)

`annualized_volatility(daily_returns)`:

- **Simple daily returns** from consecutive stored closes:
  `r_t = close_t / close_{t−1} − 1`.
- **Population standard deviation** (ddof = 0) — the full available history
  is treated as the complete population, not a sample.
- **Annualization**: `σ_daily × √252` (252 trading days convention).
- Requires ≥ 2 returns; otherwise the factor is unavailable (never guessed).
- **Numerical determinism**: identical returns short-circuit to exactly `0.0`
  (zero dispersion by definition — avoids floating-point residuals such as
  `2.7e-17`), and `math.fsum` is used for exact summation elsewhere.

### Minimum data

A symbol needs ≥ 10 stored price bars (`MIN_PRICES_FOR_METRICS = 10`) before
its momentum/volatility are computed at all.

## Missing-data rules (identical to Firm Analyst)

- An unavailable factor contributes **0 points** and its weight is
  **redistributed** proportionally across the available factors.
- No value is ever fabricated or defaulted.
- Every unavailable factor produces an explicit entry in
  `data_limitations`.
- If **no** factor is computable, `score = None`, `signal = unavailable`,
  `status = UNAVAILABLE`.

## Score and confidence

- `score = Σ (points_i × weight_i) / Σ (available weights)` — rounded to 0.1.
- Confidence = `available_weight / total_weight × quality_tier` where
  quality = 0.9 (all 4 factors) / 0.75 (3) / 0.6 (≤ 2), rounded to 2 decimals.
- Signal mapping is the shared `signal_from_score()` (see
  `docs/agent_contracts.md`).

## Determinism

Same stored data ⇒ byte-identical score/confidence/factors. There is no
randomness, no time-of-day dependence, and no LLM generation anywhere in the
pipeline. Re-runs without new data produce identical scores (verified by
`test_industry_agent_relative_strength`).

## Known limitations

- Peer discovery extends beyond the 10-symbol versioned universe (curated
  candidates, NSE Nifty 500 industry peers, Gemini suggestions — all live
  Upstox-validated); companies whose sector cannot be established from any
  source still produce no peer factors (listed as limitations).
- Momentum uses calendar-day windows over stored trading days; halts or
  sparse history shift the effective measurement window.
- Net margins compare the latest available filing periods, which may not be
  identical calendar periods across peers (period ends are stored and
  surfaced in evidence).
- Volatility from short histories (< ~30 returns) is noisy; the factor is
  still computed when ≥ 10 bars exist, and confidence reflects coverage.