"""Price-series statistics on daily closes (oldest first). Pure functions, no I/O."""

import math
import statistics
from collections.abc import Sequence

TRADING_DAYS = 252


def sma(closes: Sequence[float], n: int) -> float | None:
    return sum(closes[-n:]) / n if len(closes) >= n else None


def period_return(closes: Sequence[float], n: int) -> float | None:
    """Return over the last ``n`` sessions as a fraction."""
    if len(closes) <= n or closes[-1 - n] <= 0:
        return None
    return closes[-1] / closes[-1 - n] - 1.0


def rsi(closes: Sequence[float], n: int = 14) -> float | None:
    """Wilder's relative strength index."""
    if len(closes) <= n:
        return None
    deltas = [b - a for a, b in zip(closes[:-1], closes[1:], strict=True)]
    gain = sum(max(d, 0.0) for d in deltas[:n]) / n
    loss = sum(max(-d, 0.0) for d in deltas[:n]) / n
    for d in deltas[n:]:
        gain = (gain * (n - 1) + max(d, 0.0)) / n
        loss = (loss * (n - 1) + max(-d, 0.0)) / n
    if loss == 0:
        return 100.0
    return 100.0 - 100.0 / (1.0 + gain / loss)


def annualized_volatility(closes: Sequence[float], n: int = 126) -> float | None:
    window = closes[-(n + 1) :]
    if len(window) < 21:
        return None
    logs = [math.log(b / a) for a, b in zip(window[:-1], window[1:], strict=True) if a > 0 < b]
    return statistics.pstdev(logs) * math.sqrt(TRADING_DAYS) if len(logs) > 1 else None


def max_drawdown(closes: Sequence[float], n: int = TRADING_DAYS) -> float | None:
    """Largest peak-to-trough fall over the window, as a negative fraction."""
    window = closes[-n:]
    if len(window) < 2:
        return None
    peak, worst = window[0], 0.0
    for c in window:
        peak = max(peak, c)
        worst = min(worst, c / peak - 1.0)
    return worst


def beta(asset: Sequence[float], market: Sequence[float], n: int = TRADING_DAYS) -> float | None:
    """Beta of daily returns over the last ``n`` aligned sessions."""
    k = min(len(asset), len(market), n + 1)
    if k < 61:
        return None
    a, m = asset[-k:], market[-k:]
    ra = [y / x - 1 for x, y in zip(a[:-1], a[1:], strict=True)]
    rm = [y / x - 1 for x, y in zip(m[:-1], m[1:], strict=True)]
    var = statistics.pvariance(rm)
    if var == 0:
        return None
    mean_a, mean_m = statistics.fmean(ra), statistics.fmean(rm)
    cov = sum((x - mean_a) * (y - mean_m) for x, y in zip(ra, rm, strict=True)) / len(ra)
    return cov / var


def align_closes(
    a: Sequence[tuple[int, float]], b: Sequence[tuple[int, float]]
) -> tuple[list[float], list[float]]:
    """Closes on the dates present in both series (time keys are session start, UTC seconds)."""
    days_b = {t // 86400: c for t, c in b}
    pairs = [(c, days_b[t // 86400]) for t, c in a if t // 86400 in days_b]
    return [x for x, _ in pairs], [y for _, y in pairs]
