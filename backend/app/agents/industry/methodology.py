"""Industry Analyst scoring methodology — fully documented, deterministic.

Answers: "How attractive is the company's industry/sector environment and how
does the company compare with relevant peers?"

Factors and weights (sum = 1.0):

1. peer_momentum (weight 0.30)
   - Median 90-day momentum of sector peers (from stored prices)
   - Score: -20% → 0 pts, +20% → 100 pts (linear, capped)

2. relative_strength (weight 0.30)
   - Company 90-day momentum minus peer-median momentum
   - Score: -10pp → 0 pts, +10pp → 100 pts (linear, capped)

3. peer_fundamentals (weight 0.25)
   - Company net margin vs peer-median net margin (where filings exist)
   - Score: -10pp below median → 0 pts, +10pp above → 100 pts

4. sector_volatility (weight 0.15)
   - Company annualized volatility vs peer-median volatility
   - Lower volatility than peers scores higher
   - Score: 2× median vol → 0 pts, 0.5× median vol → 100 pts

Missing data rules: same as Firm Analyst — unavailable factors get 0 points
with weight redistributed; no fabrication; confidence = coverage × quality.

Peer group: universe entries sharing the company's sector (industry peers
when the sector has < 3 members). The company itself is excluded from peer
medians.
"""

from __future__ import annotations

from dataclasses import dataclass

WEIGHTS = {
    "peer_momentum": 0.30,
    "relative_strength": 0.30,
    "peer_fundamentals": 0.25,
    "sector_volatility": 0.15,
}

MOMENTUM_MIN, MOMENTUM_MAX = -0.20, 0.20
REL_STRENGTH_MIN, REL_STRENGTH_MAX = -0.10, 0.10
MARGIN_REL_MIN, MARGIN_REL_MAX = -0.10, 0.10
VOL_RATIO_WORST, VOL_RATIO_BEST = 2.0, 0.5

MOMENTUM_WINDOW_DAYS = 90
MIN_PRICES_FOR_METRICS = 10


@dataclass
class FactorComputation:
    name: str
    value: float | None
    points: float | None
    available: bool
    detail: str


def linear_score(value: float, worst: float, best: float) -> float:
    if worst == best:
        return 0.0
    fraction = (value - worst) / (best - worst)
    return max(0.0, min(100.0, fraction * 100.0))


def combine_factor_scores(computations: list[FactorComputation]) -> tuple[float | None, float]:
    available = [c for c in computations if c.available and c.points is not None]
    if not available:
        return None, 0.0

    available_weight = sum(WEIGHTS[c.name] for c in available)
    total_weight = sum(WEIGHTS.values())

    score = 0.0
    for c in available:
        score += c.points * (WEIGHTS[c.name] / available_weight)

    n = len(available)
    quality = 0.9 if n >= 4 else (0.75 if n >= 3 else 0.6)
    confidence = (available_weight / total_weight) * quality
    return round(score, 1), round(min(1.0, confidence), 2)


def median(values: list[float]) -> float | None:
    """Deterministic median (None for empty input)."""
    if not values:
        return None
    s = sorted(values)
    n = len(s)
    mid = n // 2
    if n % 2 == 1:
        return s[mid]
    return (s[mid - 1] + s[mid]) / 2


def annualized_volatility(daily_returns: list[float]) -> float | None:
    """Population std-dev of daily returns × sqrt(252). None if < 2 returns."""
    if len(daily_returns) < 2:
        return None
    n = len(daily_returns)
    mean = sum(daily_returns) / n
    var = sum((r - mean) ** 2 for r in daily_returns) / n
    return var ** 0.5 * (252 ** 0.5)