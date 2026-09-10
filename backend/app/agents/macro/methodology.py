"""Macro Analyst methodology — fully documented, deterministic.

Answers: "What does the broader macro environment look like for Indian
equities?" — NEVER "should I buy stock X". The output vocabulary is
POSITIVE / NEUTRAL / NEGATIVE (environment), never buy/sell.

## The seven areas and their rules

1. growth — latest real-GDP YoY vs POTENTIAL_GDP (7.0%, Economic Survey
   FY27: "potential growth estimated at around 7 per cent").
   ≥ 7.0 → POSITIVE · 6.0–7.0 → NEUTRAL · < 6.0 → NEGATIVE.
   Direction = slope sign over the last TREND_WINDOW_Q quarters.
2. inflation — latest CPI YoY vs the RBI's 4% ± 2% target band (official).
   < 2.0 → NEUTRAL (below tolerance: demand watch) · 2.0–4.0 → POSITIVE ·
   4.0–6.0 → NEUTRAL · > 6.0 → NEGATIVE.
   Direction = sign of change vs 3 observations ago.
3. interest_rates — repo level + last-meeting direction.
   Last decision ≤ −0.25pp → POSITIVE (easing) · ≥ +0.25pp → NEGATIVE ·
   else NEUTRAL. Stance wording reported, never scored.
4. liquidity_credit — UNAVAILABLE until a reliable series is configured.
   No proxy is invented (an VIX-style risk gauge is not liquidity).
5. policy — FACTS: repo decisions in the trailing 12M + current stance;
   INTERPRETATION (labeled as such): net 12M change ≤ −0.50pp → POSITIVE
   tilt · ≥ +0.50pp → NEGATIVE tilt · else NEUTRAL. Fiscal developments
   have no feed → explicit limitation, never inferred.
6. global — four gauges (USD/INR, Brent, US 10Y, India VIX), each voted
   +1/0/−1 by 3-month direction beyond a materiality floor, with fixed
   favorability signs (INR depreciation, crude rise, US-yield rise and VIX
   rise are all NEGATIVE for Indian equities). Factor signal = majority
   vote of the four sub-signals. No weights, no tuning.
7. events — informational by design: dated events detected in retrieved
   data (repo decisions, latest CPI/GDP prints). Signal always NEUTRAL;
   upcoming events have no calendar source → explicit limitation.

## Overall signal, score and confidence

Overall = majority vote of available factor signals (+1/0/−1 each).
The Macro Environment Score maps that same vote onto 0–100:

    score = 50 + 50 × (net_votes / n_available)      (None when nothing is available)

Unavailable areas are EXCLUDED from the denominator — never counted as
neutral, positive or negative. The score is a linear rescaling of the vote,
so it always agrees with the majority signal (score > 50 ⟺ POSITIVE,
score = 50 ⟺ NEUTRAL, score < 50 ⟺ NEGATIVE); it adds granularity, not a
second opinion. Like the signal, the score describes the macro environment
only — it is not a stock score and must never be blended with company
analyst scores into an investment rating.

Confidence = 0.5 × coverage + 0.3 × recency + 0.2 × consistency, where
coverage = available/7, recency = share of available factors whose data is
within their freshness window, consistency = 1 − population std-dev of the
signed factor signals. Status: 0 available → UNAVAILABLE; < 4 available →
DEGRADED; else OK. All constants below are documented and testable;
changing them is a methodology change.
"""

from __future__ import annotations

import math
from datetime import date

# --- Benchmarks (official anchors, not fitted) --------------------------------
POTENTIAL_GDP = 7.0          # Economic Survey FY27: potential growth ~7%
CPI_TARGET = 4.0             # RBI flexible inflation target
CPI_TOLERANCE = 2.0          # ±2pp tolerance band
RATE_MOVE_PP = 0.25          # one standard MPC step (percentage points)
POLICY_NET_PP = 0.50         # 12M net-change bar for a policy tilt

# --- Windows -------------------------------------------------------------------
TREND_WINDOW_Q = 5           # quarters used for the GDP slope sign
CPI_CHANGE_LAG = 3           # observations back for the inflation direction
MARKET_TREND_SESSIONS = 63   # ≈3 trading months for market gauge direction

# --- Materiality floors: a smaller move is noise, not direction ----------------
# (centralized here with rationale; change only as a methodology update)
MATERIALITY_PCT = {
    "usd_inr": 0.015,        # FX: sub-1.5% quarterly drift is noise
    "brent_crude": 0.05,     # crude: sub-5% moves reverse routinely
    "india_vix": 0.15,       # VIX: sub-15% wiggles are regime noise
}
US10Y_ABS_BPS = 25.0         # US 10Y: yields move in basis points, so the
                             # floor is absolute (±25 bps), not relative

# --- Freshness windows (days): market series move daily, official series move
# on release calendars (CPI ~monthly, GDP quarterly, MPC bimonthly) ------------
FRESHNESS_DAYS = {
    "market": 14,
    "cpi_yoy": 45,
    "gdp_real_yoy": 120,
    "repo_rate": 120,
}

# --- Coverage bar ---------------------------------------------------------------
MIN_FACTORS_OK = 4           # fewer available factors → DEGRADED

# Favorability of an UP move per market gauge (down = inverse).
# INR depreciation, costlier crude, higher US yields and higher VIX all
# tighten conditions for Indian equities → up is NEGATIVE for each.
GAUGE_UP_FAVORABLE = {
    "usd_inr": False,
    "brent_crude": False,
    "us10y": False,
    "india_vix": False,
}


# -- pure helpers ---------------------------------------------------------------

def sign_of(value: float, floor: float = 0.0) -> int:
    """+1 / 0 / −1 with a dead zone: |value| ≤ floor counts as flat."""
    if value > floor:
        return 1
    if value < -floor:
        return -1
    return 0


def slope_sign(values: list[float]) -> int:
    """Sign of the least-squares slope (needs ≥ 2 points, else 0)."""
    n = len(values)
    if n < 2:
        return 0
    xs = list(range(n))
    mean_x = sum(xs) / n
    mean_y = sum(values) / n
    denom = sum((x - mean_x) ** 2 for x in xs)
    if denom == 0:
        return 0
    slope = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, values)) / denom
    return sign_of(slope)


def majority_signal(votes: list[int]) -> str:
    """Majority vote over signed signals: 'positive' | 'neutral' | 'negative'."""
    total = sum(votes)
    if total > 0:
        return "positive"
    if total < 0:
        return "negative"
    return "neutral"


def macro_score(votes: list[int]) -> float | None:
    """0–100 Macro Environment Score from available-factor votes only.

    Each vote is +1 (positive), 0 (neutral) or −1 (negative); unavailable
    areas contribute no vote at all. Returns None when there are no votes.
    """
    if not votes:
        return None
    return round(50.0 + 50.0 * (sum(votes) / len(votes)), 1)


def signal_from_macro_score(score: float) -> str:
    """Environment signal consistent with the score by construction:
    above 50 is positive, below 50 negative, exactly 50 neutral — the same
    verdict the majority vote gives, since both reduce to the sign of the
    net vote."""
    if score > 50:
        return "positive"
    if score < 50:
        return "negative"
    return "neutral"


def population_std(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    return math.sqrt(sum((v - mean) ** 2 for v in values) / len(values))


def combine_confidence(coverage: float, recency: float, consistency: float) -> float:
    """Deterministic confidence: 0.5·coverage + 0.3·recency + 0.2·consistency."""
    return round(
        max(0.0, min(1.0, 0.5 * coverage + 0.3 * recency + 0.2 * consistency)), 2
    )


def factor_confidence(full_inputs: bool, fresh: bool) -> float:
    """Per-factor confidence from input completeness and freshness.

    Full inputs + fresh data → 0.9 · full but stale, or thin but fresh → 0.6
    (thin inputs are still scored honestly, just held lightly) · thin and
    stale → 0.5 · unavailable factors carry 0.0 (set by callers).
    """
    if full_inputs and fresh:
        return 0.9
    if full_inputs or fresh:
        return 0.6
    return 0.5


def is_fresh(latest: date | None, window_days: int, today: date | None = None) -> bool:
    """A series is fresh when its latest observation is within its window."""
    if latest is None:
        return False
    today = today or date.today()
    return (today - latest).days <= window_days
