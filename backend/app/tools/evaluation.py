"""Out-of-sample evaluation of research signals. Pure Python, no I/O.

A signal is a score per stock on a date. Its value is judged by what happened next: the
cross-sectional rank correlation (information coefficient, IC) between scores and the
following returns, and the return of the top-scored stocks over the whole universe after
costs. The verdict rules are fixed in advance (see ``verdict``) so a result cannot be argued
into significance after the fact.
"""

import math
import random
import statistics
from collections.abc import Sequence
from dataclasses import dataclass

MIN_STOCKS = 10  # cross-section size needed for a date to count
MIN_MONTHS = 24  # below this a signal is "insufficient"
EVIDENCE_MONTHS = 36
EVIDENCE_T = 2.5  # stricter than 2.0: several signals are tested at once


def _ranks(values: Sequence[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def spearman(x: Sequence[float], y: Sequence[float]) -> float | None:
    n = len(x)
    if n < 3 or len(set(x)) < 2 or len(set(y)) < 2:
        return None
    rx, ry = _ranks(x), _ranks(y)
    mx, my = sum(rx) / n, sum(ry) / n
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry, strict=True))
    vx = sum((a - mx) ** 2 for a in rx)
    vy = sum((b - my) ** 2 for b in ry)
    return cov / math.sqrt(vx * vy) if vx > 0 and vy > 0 else None


@dataclass
class Period:
    date: str  # ISO date of the signal
    scores: dict[str, float]  # symbol -> score (None-free)
    forward: dict[str, float]  # symbol -> next-period return


def ic_series(periods: Sequence[Period]) -> list[tuple[str, float, int]]:
    out = []
    for p in periods:
        common = [s for s in p.scores if s in p.forward]
        if len(common) < MIN_STOCKS:
            continue
        ic = spearman([p.scores[s] for s in common], [p.forward[s] for s in common])
        if ic is not None:
            out.append((p.date, ic, len(common)))
    return out


def block_bootstrap_mean(
    values: Sequence[float], block: int = 3, samples: int = 1000, seed: int = 17
) -> tuple[float, float] | None:
    """5th and 95th percentile of the mean, resampling blocks of consecutive periods."""
    n = len(values)
    if n < block * 4:
        return None
    rng = random.Random(seed)
    means = []
    for _ in range(samples):
        picked: list[float] = []
        while len(picked) < n:
            s = rng.randrange(n - block + 1)
            picked.extend(values[s : s + block])
        means.append(sum(picked[:n]) / n)
    means.sort()
    return means[int(0.05 * (samples - 1))], means[int(0.95 * (samples - 1))]


def t_stat(values: Sequence[float]) -> float | None:
    n = len(values)
    if n < 3:
        return None
    sd = statistics.stdev(values)
    return statistics.fmean(values) / (sd / math.sqrt(n)) if sd > 0 else None


def top_minus_universe(
    periods: Sequence[Period], fraction: float = 0.2, cost_rate: float = 0.0032
) -> list[float]:
    """Per period: equal-weight return of the top ``fraction`` by score minus the equal-weight
    universe return, less ``cost_rate`` x the share of the top bucket that changed (a round
    trip of Indian delivery charges by default)."""
    out = []
    prev: set[str] = set()
    for p in periods:
        common = [s for s in p.scores if s in p.forward]
        if len(common) < MIN_STOCKS:
            prev = set()
            continue
        k = max(1, int(len(common) * fraction))
        top = sorted(common, key=lambda s: -p.scores[s])[:k]
        top_ret = statistics.fmean(p.forward[s] for s in top)
        uni_ret = statistics.fmean(p.forward[s] for s in common)
        turnover = 1.0 if not prev else len(set(top) - prev) / k
        out.append(top_ret - uni_ret - turnover * cost_rate)
        prev = set(top)
    return out


@dataclass
class Summary:
    months: int
    avg_stocks: float
    mean_ic: float | None
    ic_t: float | None
    ic_low: float | None
    ic_high: float | None
    hit_rate: float | None
    first_half: float | None
    second_half: float | None
    spread_annual: float | None
    spread_t: float | None
    by_year: list[tuple[int, float, int]]
    verdict: str
    verdict_text: str


def verdict(s: "Summary") -> tuple[str, str]:
    """Pre-registered rules. Evidence needs 36+ months, |t| >= 2.5, a bootstrap interval that
    excludes zero, and the same sign in both halves of the history."""
    if s.months < MIN_MONTHS or s.mean_ic is None:
        return (
            "insufficient",
            f"Only {s.months} months can be tested; {MIN_MONTHS} are needed for a judgement.",
        )
    sign = 1 if s.mean_ic > 0 else -1
    consistent = (
        s.first_half is not None
        and s.second_half is not None
        and s.first_half * sign > 0
        and s.second_half * sign > 0
    )
    excludes_zero = s.ic_low is not None and s.ic_high is not None and s.ic_low * s.ic_high > 0
    strong = s.ic_t is not None and abs(s.ic_t) >= EVIDENCE_T
    if s.months >= EVIDENCE_MONTHS and strong and excludes_zero and consistent:
        if sign > 0:
            return "evidence", "Higher scores were followed by better returns, consistently."
        return "negative", "Higher scores were followed by worse returns, consistently."
    return (
        "inconclusive",
        "The relationship with later returns is too weak or unstable to rely on.",
    )


def summarize(periods: Sequence[Period], cost_rate: float = 0.0032) -> Summary:
    ics = ic_series(periods)
    values = [ic for _, ic, _ in ics]
    n = len(values)
    half = n // 2
    spread = top_minus_universe(periods, cost_rate=cost_rate)
    years: dict[int, list[float]] = {}
    for d, ic, _ in ics:
        years.setdefault(int(d[:4]), []).append(ic)
    ci = block_bootstrap_mean(values)
    s = Summary(
        months=n,
        avg_stocks=statistics.fmean(c for _, _, c in ics) if ics else 0.0,
        mean_ic=statistics.fmean(values) if values else None,
        ic_t=t_stat(values),
        ic_low=ci[0] if ci else None,
        ic_high=ci[1] if ci else None,
        hit_rate=sum(1 for v in values if v > 0) / n if n else None,
        first_half=statistics.fmean(values[:half]) if half >= 3 else None,
        second_half=statistics.fmean(values[half:]) if n - half >= 3 else None,
        spread_annual=statistics.fmean(spread) * 12 if len(spread) >= 3 else None,
        spread_t=t_stat(spread),
        by_year=[(y, statistics.fmean(v), len(v)) for y, v in sorted(years.items())],
        verdict="",
        verdict_text="",
    )
    s.verdict, s.verdict_text = verdict(s)
    return s


def timing_summary(pairs: Sequence[tuple[str, float, float]]) -> Summary:
    """A market-wide signal (one score per date) against the market's next-period return.
    ``pairs`` are (ISO date, score, forward market return). The IC is the rank correlation
    across dates; the spread is the annualised market return in positive-score months minus
    negative-score months."""
    n = len(pairs)
    scores = [s for _, s, _ in pairs]
    fwd = [r for _, _, r in pairs]
    ic = spearman(scores, fwd) if n >= 3 else None
    t = ic * math.sqrt((n - 2) / max(1e-12, 1 - ic * ic)) if ic is not None and n > 2 else None
    half = n // 2

    def part(lo: int, hi: int) -> float | None:
        return spearman(scores[lo:hi], fwd[lo:hi]) if hi - lo >= 6 else None

    ci = None
    if n >= 12:
        rng = random.Random(17)
        draws = []
        for _ in range(1000):
            idx: list[int] = []
            while len(idx) < n:
                s = rng.randrange(n - 2)
                idx.extend(range(s, s + 3))
            idx = idx[:n]
            v = spearman([scores[i] for i in idx], [fwd[i] for i in idx])
            if v is not None:
                draws.append(v)
        draws.sort()
        if draws:
            ci = (draws[int(0.05 * (len(draws) - 1))], draws[int(0.95 * (len(draws) - 1))])
    pos = [r for s, r in zip(scores, fwd, strict=True) if s > 0]
    neg = [r for s, r in zip(scores, fwd, strict=True) if s < 0]
    years: dict[int, list[tuple[float, float]]] = {}
    for d, s, r in pairs:
        years.setdefault(int(d[:4]), []).append((s, r))
    by_year = []
    for y, v in sorted(years.items()):
        c = spearman([a for a, _ in v], [b for _, b in v]) if len(v) >= 6 else None
        if c is not None:
            by_year.append((y, c, len(v)))
    out = Summary(
        months=n,
        avg_stocks=1.0,
        mean_ic=ic,
        ic_t=t,
        ic_low=ci[0] if ci else None,
        ic_high=ci[1] if ci else None,
        hit_rate=None,
        first_half=part(0, half),
        second_half=part(half, n),
        spread_annual=(statistics.fmean(pos) - statistics.fmean(neg)) * 12 if pos and neg else None,
        spread_t=None,
        by_year=by_year,
        verdict="",
        verdict_text="",
    )
    out.verdict, out.verdict_text = verdict(out)
    return out
