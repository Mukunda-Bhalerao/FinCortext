# Macro Analyst — Methodology

> Implementation: `backend/app/agents/macro/`
> (`methodology.py`, `macro_agent.py`)
> Data: `backend/app/data/macro/`, `app/services/macro_service.py`,
> `app/repositories/macro_repository.py`
> Version: `macro_analyst_v1` (recorded in every output's `methodology`)

## Purpose

The Macro Analyst answers:

> "What does the broader macro environment look like for Indian equities?"

It is market-wide, not company-specific: the same output applies to TCS,
INFY, or any universe company. Its vocabulary is POSITIVE / NEUTRAL /
NEGATIVE (**environment**), never buy/sell — a positive environment is not a
recommendation for any stock. It carries a 0–100 Macro Environment Score (a
linear rescaling of the available-factor vote, always agreeing with the
signal) for granularity — but the score describes the environment only and
must never be blended with company analyst scores into an investment rating.

## Pipeline

```
official releases (RBI/MoSPI, curated CSVs) + market gauges (yfinance)
    → MacroDataProvider adapters (curated_official, yfinance_macro)
    → validation (finite values, real non-future periods, de-duplicated)
    → MacroService (per-indicator isolation, provenance) → DuckDB
    → MacroAgent: 7 deterministic factors → majority-vote overall signal
    → MacroOutput → API → frontend
```

Agents never touch HTTP: all retrieval happens in providers/services.

## The seven areas

| # | Area | Inputs | Signal rule |
|---|---|---|---|
| 1 | Growth | Real-GDP YoY quarters (MoSPI, curated) | ≥ 7.0% POSITIVE (potential ~7%, Economic Survey FY27); 6.0–7.0 NEUTRAL; < 6.0 NEGATIVE. Direction = 5-quarter slope sign. |
| 2 | Inflation | CPI YoY months (MoSPI, curated) | RBI 4% ± 2% band: < 2 NEUTRAL (demand watch); 2–4 POSITIVE; 4–6 NEUTRAL; > 6 NEGATIVE. Direction = 3-observation change. |
| 3 | Interest Rates | Repo-rate decisions (RBI, curated) | Last move ≤ −0.25pp POSITIVE (easing); ≥ +0.25pp NEGATIVE; else NEUTRAL. Stance reported, never scored. |
| 4 | Liquidity & Credit | none configured | Always UNAVAILABLE — no proxy is invented. |
| 5 | Fiscal & Monetary Policy | Repo decisions, trailing 12M | Net 12M ≤ −0.50pp POSITIVE tilt; ≥ +0.50pp NEGATIVE; else NEUTRAL. Fiscal has no feed → always an explicit limitation. Facts (dated decisions) and interpretation (tilt sentence) are labeled separately. |
| 6 | Global Markets | USD/INR, Brent, US 10Y, India VIX (yfinance) | Each gauge votes +1/0/−1 by ~3M direction beyond a materiality floor (FX 1.5%, crude 5%, US10Y 25 bps absolute, VIX 15%); up-moves are adverse for all four. Factor = majority vote. |
| 7 | Macro Events | Dated repo decisions + latest CPI/GDP prints | Informational by design: always NEUTRAL. Upcoming events have no calendar source and are not listed. |

All thresholds live in `methodology.py` with rationale; changing them is a
methodology change and must be reflected in tests.

## Overall signal, score and confidence

Overall = majority vote of available factor signals (+1/0/−1 each, unavailable
areas excluded from the denominator — never counted as neutral). The Macro
Environment Score maps that same vote onto 0–100: `score = 50 + 50 ×
(net_votes / n_available)` (None when nothing is available). The score always
agrees with the signal (score > 50 ⟺ POSITIVE, score = 50 ⟺ NEUTRAL, score <
50 ⟺ NEGATIVE); it adds granularity, not a second opinion.
Confidence =
0.5·coverage + 0.3·recency + 0.2·consistency, where coverage = available/7,
recency = share of available factors within their freshness window (market
14d, CPI 45d, GDP/repo 120d), consistency = 1 − std-dev of signed signals.
Status: 0 available → UNAVAILABLE; < 4 → DEGRADED; else OK.

Per-factor confidence: 0.9 (full fresh inputs) / 0.6 (full-but-stale or
thin-but-fresh) / 0.5 (thin and stale) / 0.0 (unavailable).

## Status semantics (honest degradation)

| situation | status |
|---|---|
| no indicator has usable history | UNAVAILABLE (no signal, confidence 0) |
| fewer than 4 of 7 areas available | DEGRADED |
| 4+ areas available | OK |

The backend never crashes on provider problems — per-indicator failures are
isolated and reported; the analysis runs on whatever valid data exists.

## Output contents

- `overall_signal`, `score` (0–100 environment score, None when unavailable),
  `confidence`, `status`
- 7 factors: value, unit, direction, signal, confidence, availability,
  `data_as_of`, detail, evidence (retrieved facts with sources), limitations
- rationale: dated FACTS paragraph + labeled INTERPRETATION sentence
- `data_through`: per-indicator latest observation date
- provenance: methodology, factors available/total, requested symbol

## Data model and point-in-time honesty

`macro_observations`: indicator, value, unit, period dates, observed date,
publication/release date, `available_at` (falls back to ingestion time),
source name/URL, content hash, notes. Observation ids are deterministic
hashes, so re-ingesting identical data replaces rather than duplicates.
GDP base vintages (2011-12 → 2022-23) are recorded per row and surfaced in
evidence — rebasing never silently mixes vintages in reading.

## Known limitations

- Liquidity/credit and fiscal developments have no configured source and
  report as unavailable/limited rather than proxied.
- Curated official series update by committing new verified CSV versions —
  there is no live RBI/MoSPI feed (DBnomics is unreachable from this
  environment; RBI site scraping is out of scope).
- Upcoming-event calendars are not covered.
- Market gauges need ~1 quarter of history before they vote.
