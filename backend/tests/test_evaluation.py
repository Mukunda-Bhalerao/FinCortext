import random
from datetime import date

from app.services.signal_lab import pit_fundamentals
from app.tools import evaluation as E


def _periods(signal_strength: float, months: int = 48, stocks: int = 40, seed: int = 5):
    rng = random.Random(seed)
    out = []
    for m in range(months):
        scores = {f"S{i}": rng.gauss(0, 1) for i in range(stocks)}
        forward = {s: signal_strength * v * 0.01 + rng.gauss(0, 0.05) for s, v in scores.items()}
        out.append(E.Period(f"{2018 + m // 12}-{m % 12 + 1:02d}-01", scores, forward))
    return out


def test_spearman_handles_ties_and_constants():
    assert E.spearman([1, 2, 3, 4], [10, 20, 30, 40]) == 1.0
    assert E.spearman([1, 2, 3, 4], [4, 3, 2, 1]) == -1.0
    assert E.spearman([1, 1, 1], [1, 2, 3]) is None


def test_strong_signal_earns_evidence_and_noise_does_not():
    strong = E.summarize(_periods(3.0))
    assert strong.verdict == "evidence" and strong.mean_ic > 0.2 and strong.spread_annual > 0
    noise = E.summarize(_periods(0.0))
    assert noise.verdict == "inconclusive"
    reversed_ = E.summarize(_periods(-3.0))
    assert reversed_.verdict == "negative"


def test_short_history_is_insufficient():
    assert E.summarize(_periods(3.0, months=12)).verdict == "insufficient"


def test_small_cross_sections_are_skipped():
    assert E.ic_series(_periods(3.0, stocks=5)) == []


def test_timing_summary_detects_a_market_signal():
    rng = random.Random(3)
    pairs = []
    for m in range(60):
        s = rng.gauss(0, 1)
        pairs.append((f"{2018 + m // 12}-{m % 12 + 1:02d}-01", s, 0.02 * s + rng.gauss(0, 0.01)))
    out = E.timing_summary(pairs)
    assert out.verdict == "evidence" and out.spread_annual > 0


def test_pit_fundamentals_respect_the_reporting_lag():
    rows = [
        ("annualNetIncome", date(2024, 3, 31), 100.0),
        ("annualTotalRevenue", date(2024, 3, 31), 1000.0),
        ("annualStockholdersEquity", date(2024, 3, 31), 500.0),
        ("annualNetIncome", date(2025, 3, 31), 150.0),
        ("annualTotalRevenue", date(2025, 3, 31), 1100.0),
        ("annualStockholdersEquity", date(2025, 3, 31), 600.0),
    ]
    assert pit_fundamentals("X", rows, date(2024, 6, 1)) is None  # FY24 not yet published
    f = pit_fundamentals("X", rows, date(2025, 5, 1))
    assert f.roe == 100 / 500 and f.revenue_growth is None  # FY25 still 75 days away
    g = pit_fundamentals("X", rows, date(2025, 7, 1))
    assert g.roe == 150 / 600 and abs(g.revenue_growth - 0.1) < 1e-12
    assert abs(g.earnings_growth - 0.5) < 1e-12 and g.trailing_pe is None
