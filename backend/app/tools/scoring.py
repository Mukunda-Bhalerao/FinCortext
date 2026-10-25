"""Score arithmetic shared by the research agents. Pure functions, no I/O."""

import statistics
from collections.abc import Sequence

SIGNAL_THRESHOLD = 0.2
MIN_COVERAGE = 0.4


def scale(value: float, lo: float, hi: float) -> float:
    """Linear map of ``lo -> -1`` and ``hi -> +1``, clamped. ``lo > hi`` inverts the direction."""
    if hi == lo:
        return 0.0
    return max(-1.0, min(1.0, 2.0 * (value - lo) / (hi - lo) - 1.0))


def weighted(parts: Sequence[tuple[float | None, float]]) -> tuple[float | None, float]:
    """Weighted mean of the scored parts and the share of total weight that had a score."""
    total = sum(w for _, w in parts)
    scored = [(s, w) for s, w in parts if s is not None and w > 0]
    have = sum(w for _, w in scored)
    if not scored or total <= 0:
        return None, 0.0
    return sum(s * w for s, w in scored) / have, have / total


def agreement(scores: Sequence[float]) -> float:
    """1.0 when all factor scores agree; falls toward 0 as they spread across -1..1."""
    if len(scores) < 2:
        return 0.5
    return max(0.0, 1.0 - statistics.pstdev(scores))


def confidence(coverage: float, scores: Sequence[float], quality: float = 1.0) -> float:
    """Coverage of the factor weights, discounted for disagreement and source quality."""
    return round(max(0.0, min(1.0, coverage * (0.6 + 0.4 * agreement(scores)) * quality)), 2)


def signal_for(score: float | None, coverage: float) -> str:
    if score is None or coverage < MIN_COVERAGE:
        return "insufficient_data"
    if score >= SIGNAL_THRESHOLD:
        return "positive"
    if score <= -SIGNAL_THRESHOLD:
        return "negative"
    return "neutral"


def percentile_rank(value: float, population: Sequence[float]) -> float:
    """Share of the population strictly below ``value``, counting ties as half."""
    if not population:
        return 0.5
    below = sum(1 for v in population if v < value)
    ties = sum(1 for v in population if v == value)
    return (below + 0.5 * ties) / len(population)


def median(values: Sequence[float | None]) -> float | None:
    present = [v for v in values if v is not None]
    return statistics.median(present) if present else None
