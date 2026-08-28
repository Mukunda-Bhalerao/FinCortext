"""Firm Analyst scoring methodology — fully documented, deterministic.

SCORE = weighted sum of factor scores, each mapped to 0–100 points.

Factors and weights (sum = 1.0):

1. profitability (weight 0.25)
   - Inputs: net_income, total_revenue (same period)
   - net_margin = net_income / total_revenue
   - Score: margin mapped linearly, 0% → 0 points, 20%+ → 100 points
     (capped). Indian large-cap net margins typically range 0–30%.

2. revenue_growth (weight 0.20)
   - Inputs: total_revenue current vs previous period (period_end at least
     300 days earlier)
   - growth = (current - previous) / |previous|
   - Score: -10% → 0 points, +25% → 100 points (linear, capped)

3. financial_health (weight 0.20)
   - Inputs: total_debt, total_equity
   - debt_to_equity = total_debt / total_equity
   - Score: D/E 2.0+ → 0 points, D/E 0 → 100 points (linear, capped)

4. return_on_equity (weight 0.15)
   - Inputs: roe observation if present, else net_income / total_equity
   - Score: 0% → 0 points, 25%+ → 100 points (linear, capped)

5. valuation (weight 0.10)
   - Inputs: pe_ratio observation if present
   - Score: P/E 40+ → 0 points, P/E ≤ 10 → 100 points (linear, capped);
     missing P/E → factor unavailable (no fabrication)

6. market_momentum (weight 0.10)
   - Inputs: stored close prices (last ~90 days)
   - momentum = (latest_close / close_90d_ago) - 1
   - Score: -20% → 0 points, +20% → 100 points (linear, capped)

Missing data rules:
- A factor with missing inputs is marked unavailable, contributes 0 points,
  and its weight is redistributed proportionally across available factors.
- If NO factor is available, score is None and signal is UNAVAILABLE.

Confidence rules (deterministic):
- confidence = available_weight_fraction * quality_factor
- available_weight_fraction = (sum of weights of available factors) / 1.0
- quality_factor = 0.9 if >= 5 factors available, 0.75 if 3-4, 0.6 otherwise
- Confidence is never random and never fabricated.

All thresholds are documented here and testable. Changing them is a
methodology change and must be reflected in tests.
"""

from __future__ import annotations

from dataclasses import dataclass

# --- Weights (documented; sum to 1.0) ----------------------------------------
WEIGHTS = {
    "profitability": 0.25,
    "revenue_growth": 0.20,
    "financial_health": 0.20,
    "return_on_equity": 0.15,
    "valuation": 0.10,
    "market_momentum": 0.10,
}

# --- Factor thresholds (linear mapping bounds) --------------------------------
NET_MARGIN_MIN, NET_MARGIN_MAX = 0.0, 0.20          # 0% → 0 pts, 20% → 100 pts
GROWTH_MIN, GROWTH_MAX = -0.10, 0.25                # -10% → 0, +25% → 100
DE_MAX, DE_MIN = 2.0, 0.0                           # D/E 2.0 → 0, 0 → 100
ROE_MIN, ROE_MAX = 0.0, 0.25                        # 0% → 0, 25% → 100
PE_MAX, PE_MIN = 40.0, 10.0                         # P/E 40 → 0, 10 → 100
MOMENTUM_MIN, MOMENTUM_MAX = -0.20, 0.20            # -20% → 0, +20% → 100


@dataclass
class FactorComputation:
    """Result of computing one factor."""

    name: str
    value: float | None
    points: float | None  # 0–100
    available: bool
    detail: str


def linear_score(value: float, worst: float, best: float) -> float:
    """Map value linearly from [worst, best] to [0, 100], clamped.

    Works for both directions (worst > best supported).
    """
    if worst == best:
        return 0.0
    fraction = (value - worst) / (best - worst)
    return max(0.0, min(100.0, fraction * 100.0))


def combine_factor_scores(computations: list[FactorComputation]) -> tuple[float | None, float]:
    """Combine factor computations into (score, confidence).

    Weight redistribution: unavailable factors' weights are redistributed
    proportionally across available factors. Returns (None, 0.0) when no
    factor is available.
    """
    available = [c for c in computations if c.available and c.points is not None]
    if not available:
        return None, 0.0

    available_weight = sum(WEIGHTS[c.name] for c in available)
    total_weight = sum(WEIGHTS.values())

    score = 0.0
    for c in available:
        share = WEIGHTS[c.name] / available_weight
        score += c.points * share * (total_weight / total_weight)  # normalized to 100

    # Confidence: evidence coverage × quality factor
    n_available = len(available)
    if n_available >= 5:
        quality = 0.9
    elif n_available >= 3:
        quality = 0.75
    else:
        quality = 0.6
    confidence = (available_weight / total_weight) * quality
    return round(score, 1), round(min(1.0, confidence), 2)