"""Portfolio construction, risk and walk-forward backtesting. Pure Python, no I/O.

Conventions: ``R`` is a list of per-asset daily simple-return lists of equal length (oldest
first); weights are long-only fractions summing to 1. Annualisation uses 252 sessions.
"""

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta

TRADING_DAYS = 252
EPOCH = date(1970, 1, 1)
Matrix = list[list[float]]

# --- series alignment and returns ------------------------------------------------------


def align(
    series: dict[str, Sequence[tuple[int, float]]],
) -> tuple[list[int], dict[str, list[float]]]:
    """Closes on the sessions every series has (keyed by UTC day of the candle start)."""
    if not series:
        return [], {}
    maps = {k: {t // 86400: c for t, c in v} for k, v in series.items()}
    common = sorted(set.intersection(*(set(m) for m in maps.values())))
    return common, {k: [m[d] for d in common] for k, m in maps.items()}


def simple_returns(closes: Sequence[float]) -> list[float]:
    return [b / a - 1.0 for a, b in zip(closes[:-1], closes[1:], strict=True)]


def suspicious_jump(closes: Sequence[float], limit: float = 0.35) -> float | None:
    """Largest one-day move beyond ``limit``: a sign of an unadjusted split or bad print."""
    worst = None
    for r in simple_returns(closes):
        if abs(r) > limit and (worst is None or abs(r) > abs(worst)):
            worst = r
    return worst


# --- covariance -------------------------------------------------------------------------


def covariance(R: Sequence[Sequence[float]]) -> Matrix:
    n, t = len(R), len(R[0])
    means = [sum(r) / t for r in R]
    X = [[r[k] - means[i] for k in range(t)] for i, r in enumerate(R)]
    return [
        [sum(a * b for a, b in zip(X[i], X[j], strict=True)) / t for j in range(n)]
        for i in range(n)
    ]


def shrunk_covariance(R: Sequence[Sequence[float]]) -> tuple[Matrix, float]:
    """Ledoit-Wolf (2004) shrinkage toward a scaled identity. Returns (matrix, intensity)."""
    n, t = len(R), len(R[0])
    S = covariance(R)
    if n == 1:
        return S, 0.0
    means = [sum(r) / t for r in R]
    X = [[r[k] - means[i] for i, r in enumerate(R)] for k in range(t)]  # obs x assets
    m = sum(S[i][i] for i in range(n)) / n
    d2 = sum((S[i][j] - (m if i == j else 0.0)) ** 2 for i in range(n) for j in range(n)) / n
    b_bar = 0.0
    for x in X:
        b_bar += sum((x[i] * x[j] - S[i][j]) ** 2 for i in range(n) for j in range(n)) / n
    b_bar /= t * t
    delta = 0.0 if d2 == 0 else min(b_bar, d2) / d2
    shrunk = [
        [delta * (m if i == j else 0.0) + (1 - delta) * S[i][j] for j in range(n)] for i in range(n)
    ]
    return shrunk, delta


def correlation(S: Matrix) -> Matrix:
    sd = [math.sqrt(max(S[i][i], 0.0)) for i in range(len(S))]
    return [
        [S[i][j] / (sd[i] * sd[j]) if sd[i] and sd[j] else 0.0 for j in range(len(S))]
        for i in range(len(S))
    ]


def _mv(S: Matrix, w: Sequence[float]) -> list[float]:
    return [sum(a * b for a, b in zip(row, w, strict=True)) for row in S]


def port_variance(w: Sequence[float], S: Matrix) -> float:
    return sum(a * b for a, b in zip(w, _mv(S, w), strict=True))


def port_vol(w: Sequence[float], S: Matrix) -> float:
    """Annualised volatility from a daily covariance matrix."""
    return math.sqrt(max(port_variance(w, S), 0.0) * TRADING_DAYS)


def risk_contributions(w: Sequence[float], S: Matrix) -> list[float]:
    """Share of portfolio variance contributed by each asset (sums to 1)."""
    var = port_variance(w, S)
    if var <= 0:
        return [0.0] * len(w)
    return [wi * mi / var for wi, mi in zip(w, _mv(S, w), strict=True)]


def diversification_ratio(w: Sequence[float], S: Matrix) -> float:
    """Weighted average asset volatility over portfolio volatility (1 = no diversification)."""
    vol = math.sqrt(max(port_variance(w, S), 0.0))
    avg = sum(wi * math.sqrt(max(S[i][i], 0.0)) for i, wi in enumerate(w))
    return avg / vol if vol > 0 else 1.0


def effective_n(w: Sequence[float]) -> float:
    s = sum(x * x for x in w)
    return 1.0 / s if s > 0 else 0.0


# --- constraints ------------------------------------------------------------------------


def project_capped_simplex(v: Sequence[float], cap: float) -> list[float]:
    """Euclidean projection onto {w : 0 <= w_i <= cap, sum w = 1}."""
    n = len(v)
    cap = max(cap, 1.0 / n)
    lo, hi = min(v) - cap, max(v)
    for _ in range(100):
        tau = (lo + hi) / 2
        total = sum(min(max(x - tau, 0.0), cap) for x in v)
        if total > 1:
            lo = tau
        else:
            hi = tau
    w = [min(max(x - (lo + hi) / 2, 0.0), cap) for x in v]
    s = sum(w)
    return [x / s for x in w] if s > 0 else [1.0 / n] * n


def apply_caps(
    w: Sequence[float], cap: float, groups: Sequence[str] | None = None, group_cap: float = 1.0
) -> tuple[list[float], bool]:
    """Enforce per-asset and per-group caps by moving excess weight to assets with room.

    Returns (weights, feasible). Infeasible when the caps cannot all hold at once (for example
    two holdings with a 25% cap); the closest weights found are returned.
    """
    n = len(w)
    w = list(w)
    cap = max(cap, 1.0 / n)
    labels = list(groups) if groups else [str(i) for i in range(n)]
    for _ in range(200):
        moved = False
        for g in set(labels):
            idx = [i for i in range(n) if labels[i] == g]
            total = sum(w[i] for i in idx)
            if groups and total > group_cap + 1e-9:
                for i in idx:
                    w[i] *= group_cap / total
                moved = True
        for i in range(n):
            if w[i] > cap + 1e-9:
                w[i] = cap
                moved = True
        excess = 1.0 - sum(w)
        if abs(excess) < 1e-9 and not moved:
            return w, True
        if excess > 1e-12:
            group_tot = {g: sum(w[i] for i in range(n) if labels[i] == g) for g in set(labels)}
            room = [
                i
                for i in range(n)
                if w[i] < cap - 1e-9 and (not groups or group_tot[labels[i]] < group_cap - 1e-9)
            ]
            if not room:
                s = sum(w)
                return [x / s for x in w], False
            room_total = sum(w[i] for i in room)
            for i in room:
                w[i] += excess * (w[i] / room_total if room_total > 0 else 1 / len(room))
    s = sum(w)
    return [x / s for x in w], False


# --- weighting schemes ---------------------------------------------------------------------


def equal_weight(S: Matrix) -> list[float]:
    return [1.0 / len(S)] * len(S)


def inverse_volatility(S: Matrix) -> list[float]:
    inv = [1.0 / math.sqrt(S[i][i]) if S[i][i] > 0 else 0.0 for i in range(len(S))]
    total = sum(inv)
    return [x / total for x in inv] if total else equal_weight(S)


def _max_eigen(S: Matrix) -> float:
    v = [1.0] * len(S)
    lam = 0.0
    for _ in range(50):
        u = _mv(S, v)
        lam = math.sqrt(sum(x * x for x in u))
        if lam == 0:
            return 0.0
        v = [x / lam for x in u]
    return lam


def minimum_variance(S: Matrix, cap: float, iters: int = 600) -> list[float]:
    """Long-only minimum variance under a per-asset cap, by projected gradient descent."""
    n = len(S)
    lam = _max_eigen(S)
    if lam <= 0:
        return equal_weight(S)
    step = 1.0 / (2.0 * lam)
    w = project_capped_simplex(inverse_volatility(S), cap)
    for _ in range(iters):
        g = [2.0 * x for x in _mv(S, w)]
        nxt = project_capped_simplex([wi - step * gi for wi, gi in zip(w, g, strict=True)], cap)
        if max(abs(a - b) for a, b in zip(nxt, w, strict=True)) < 1e-10:
            w = nxt
            break
        w = nxt
    return w if n else []


def risk_parity(S: Matrix, iters: int = 200) -> list[float]:
    """Equal risk contribution by cyclical coordinate descent (Griveau-Billion et al., 2013)."""
    n = len(S)
    x = inverse_volatility(S)
    b = 1.0 / n
    for _ in range(iters):
        prev = list(x)
        for i in range(n):
            a = S[i][i]
            if a <= 0:
                continue
            c = sum(S[i][j] * x[j] for j in range(n) if j != i)
            x[i] = (-c + math.sqrt(c * c + 4 * a * b)) / (2 * a)
        if max(abs(p - q) for p, q in zip(prev, x, strict=True)) < 1e-12:
            break
    total = sum(x)
    return [v / total for v in x]


def score_tilt(
    base: Sequence[float], scores: Sequence[float | None], strength: float = 0.5
) -> list[float]:
    """Scale base weights by (1 + strength x score); a missing score leaves the weight unchanged."""
    tilted = [w * max(0.0, 1.0 + strength * (s or 0.0)) for w, s in zip(base, scores, strict=True)]
    total = sum(tilted)
    return [t / total for t in tilted] if total else list(base)


# --- performance --------------------------------------------------------------------------


@dataclass
class Stats:
    cagr: float | None
    volatility: float | None
    sharpe: float | None
    max_drawdown: float | None
    total_return: float | None
    days: int


def max_drawdown(equity: Sequence[float]) -> float:
    peak, worst = equity[0] if equity else 1.0, 0.0
    for v in equity:
        peak = max(peak, v)
        worst = min(worst, v / peak - 1.0)
    return worst


def stats(daily: Sequence[float], rf_annual: float = 0.0) -> Stats:
    n = len(daily)
    if n < 20:
        return Stats(None, None, None, None, None, n)
    equity = [1.0]
    for r in daily:
        equity.append(equity[-1] * (1 + r))
    total = equity[-1] - 1
    cagr = equity[-1] ** (TRADING_DAYS / n) - 1 if equity[-1] > 0 else -1.0
    mean = sum(daily) / n
    vol = math.sqrt(sum((r - mean) ** 2 for r in daily) / (n - 1)) * math.sqrt(TRADING_DAYS)
    if vol < 1e-9:  # constant returns: avoid a meaningless ratio from rounding noise
        vol = 0.0
    sharpe = (mean * TRADING_DAYS - rf_annual) / vol if vol > 0 else None
    return Stats(cagr, vol, sharpe, max_drawdown(equity), total, n)


def fixed_weight_returns(R: Sequence[Sequence[float]], w: Sequence[float]) -> list[float]:
    """Daily returns of weights rebalanced every day (used for in-sample summaries only)."""
    return [sum(w[i] * R[i][k] for i in range(len(w))) for k in range(len(R[0]))]


WeightFn = Callable[[list[list[float]]], list[float]]


@dataclass
class Backtest:
    start_index: int
    daily: list[float]
    equity: list[float]
    rebalances: int
    turnover: float  # one-way, summed over rebalances
    costs: float  # fraction of capital paid in costs, summed
    weights_history: list[list[float]] = field(default_factory=list)


def month_starts(days: Sequence[int]) -> list[int]:
    """Indices of the first session of each calendar month (days are UTC day numbers)."""
    out = []
    prev = None
    for i, d in enumerate(days):
        m = (EPOCH + timedelta(days=d)).replace(day=1)
        if m != prev:
            out.append(i)
            prev = m
    return out


def walk_forward(
    days: Sequence[int],
    closes: Sequence[Sequence[float]],
    weight_fn: WeightFn,
    lookback: int = TRADING_DAYS,
    cost_rate: float = 0.0015,
    end: int | None = None,
) -> Backtest | None:
    """Monthly rebalanced backtest without look-ahead.

    At the close of each month's first session ``t`` the weights are computed from returns
    of sessions ``t - lookback .. t - 1`` only, traded at that close, and charged
    ``cost_rate`` per unit of capital traded. Between rebalances weights drift with prices.
    """
    end = len(days) if end is None else end
    R = [simple_returns(c[:end]) for c in closes]  # R[i][k] is the return into session k+1
    schedule = [i for i in month_starts(days[:end]) if i - 1 >= lookback]
    if not schedule or len(R[0]) == 0:
        return None
    start = schedule[0]
    n = len(closes)
    w = [0.0] * n
    daily: list[float] = []
    equity = [1.0]
    turnover = costs = 0.0
    history: list[list[float]] = []
    reb = set(schedule)
    for t in range(start, end):
        if t > start:
            r = [R[i][t - 1] for i in range(n)]
            pr = sum(w[i] * r[i] for i in range(n))
            grown = [w[i] * (1 + r[i]) for i in range(n)]
            total = sum(grown)
            w = [g / total for g in grown] if total > 0 else w
        else:
            pr = 0.0
        cost = 0.0
        if t in reb:
            window = [R[i][t - 1 - lookback : t - 1] for i in range(n)]
            target = weight_fn(window)
            traded = sum(abs(a - b) for a, b in zip(target, w, strict=True))
            if t == start:
                traded = sum(target)  # initial purchase from cash
            cost = traded * cost_rate
            turnover += traded / (2 if t != start else 1)
            costs += cost
            w = target
            history.append(target)
        day = (1 + pr) * (1 - cost) - 1
        if t > start or cost:
            daily.append(day)
            equity.append(equity[-1] * (1 + day))
    return Backtest(start, daily, equity, len(history), turnover, costs, history)
