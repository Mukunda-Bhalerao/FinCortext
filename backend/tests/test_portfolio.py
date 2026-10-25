import asyncio
import math
import random
from datetime import UTC, datetime

from app.agents.base import PriceSeries
from app.db import Database
from app.errors import NotConnected
from app.services.instruments import InstrumentService
from app.services.portfolio import PortfolioService, stock_cap, weights_for
from app.tools import backtest as B
from app.tools import portfolio as P

DAY0 = 19000  # UTC day number


def _factor_returns(n_assets: int, days: int, seed: int = 7) -> list[list[float]]:
    rng = random.Random(seed)
    f = [rng.gauss(0.0003, 0.01) for _ in range(days)]
    return [
        [0.6 * f[k] + rng.gauss(0.0002, 0.006 + 0.004 * i) for k in range(days)]
        for i in range(n_assets)
    ]


def _closes(R: list[list[float]]) -> list[list[float]]:
    out = []
    for r in R:
        c = [100.0]
        for x in r:
            c.append(c[-1] * (1 + x))
        out.append(c)
    return out


# --- math ---------------------------------------------------------------------------


def test_risk_parity_equalises_contributions():
    S, _ = P.shrunk_covariance(_factor_returns(4, 300))
    rc = P.risk_contributions(P.risk_parity(S), S)
    assert all(abs(x - 0.25) < 1e-6 for x in rc)


def test_minimum_variance_beats_equal_weight_and_respects_cap():
    S, _ = P.shrunk_covariance(_factor_returns(5, 300))
    w = P.minimum_variance(S, 0.3)
    assert abs(sum(w) - 1) < 1e-9 and max(w) <= 0.3 + 1e-9 and min(w) >= 0
    assert P.port_vol(w, S) <= P.port_vol(P.equal_weight(S), S) + 1e-12


def test_shrinkage_intensity_in_unit_interval():
    _, delta = P.shrunk_covariance(_factor_returns(6, 80))
    assert 0 <= delta <= 1


def test_caps_move_excess_to_assets_with_room():
    w, ok = P.apply_caps([0.7, 0.2, 0.1], 0.5, ["a", "a", "b"], 0.6)
    assert ok and abs(sum(w) - 1) < 1e-9
    assert w[0] <= 0.5 + 1e-9 and w[0] + w[1] <= 0.6 + 1e-9


def test_stock_cap_scales_with_holdings():
    assert stock_cap(2) == 0.75 and stock_cap(4) == 0.375 and stock_cap(10) == 0.25


def test_score_tilt_leaves_missing_scores_neutral():
    assert P.score_tilt([0.5, 0.5], [None, None]) == [0.5, 0.5]
    w = P.score_tilt([0.5, 0.5], [0.5, -0.5])
    assert w[0] > w[1]


def test_stats_and_drawdown():
    assert P.max_drawdown([1.0, 1.2, 0.9, 1.3]) == -0.25
    s = P.stats([0.001] * 252)
    assert abs(s.cagr - (1.001**252 - 1)) < 1e-9 and s.volatility == 0 and s.sharpe is None


def test_suspicious_jump_flags_unadjusted_split():
    assert P.suspicious_jump([100, 101, 50, 51]) == -0.504950495049505
    assert P.suspicious_jump([100, 101, 102]) is None


# --- backtest -----------------------------------------------------------------------------


def test_walk_forward_has_no_look_ahead_and_charges_costs():
    R = _factor_returns(3, 700)
    closes = _closes(R)
    days = list(range(DAY0, DAY0 + len(closes[0])))
    fn = lambda W: P.risk_parity(P.shrunk_covariance(W)[0])  # noqa: E731
    base = P.walk_forward(days, closes, fn, lookback=252, cost_rate=0.002)
    assert base is not None and base.rebalances > 5
    assert base.costs > 0 and base.equity[1] < 1  # initial purchase pays costs

    # Changing prices after the 3rd rebalance must not change the first three decisions.
    schedule = [i for i in P.month_starts(days) if i - 1 >= 252]
    cut = schedule[2]
    altered = [c[: cut + 1] + [x * 1.5 for x in c[cut + 1 :]] for c in closes]
    again = P.walk_forward(days, altered, fn, lookback=252, cost_rate=0.002)
    assert again.weights_history[:3] == base.weights_history[:3]
    assert again.weights_history[3:] != base.weights_history[3:]


def test_walk_forward_without_enough_history_returns_none():
    closes = _closes(_factor_returns(2, 100))
    days = list(range(DAY0, DAY0 + 101))
    assert P.walk_forward(days, closes, P.equal_weight, lookback=252) is None


def test_weights_for_reports_unapplied_sector_cap():
    S, _ = P.shrunk_covariance(_factor_returns(2, 300))
    w, ok, note = weights_for("equal_weight", S, ["IT", "Energy"], [None, None])
    assert ok and w == [0.5, 0.5] and "Sector cap not applied" in (note or "")


# --- service, offline -----------------------------------------------------------------------


class _FakeData:
    def __init__(self, series: dict[str, list[float]]):
        self.series = series

    async def daily(self, inst, label=None):
        closes = self.series.get(inst.symbol)
        if closes is None:
            raise NotConnected("Upstox is not connected.")
        times = [(DAY0 + k) * 86400 for k in range(len(closes))]
        return PriceSeries(inst.symbol, times, closes, "test", datetime.now(UTC))

    async def long_daily(self, inst):
        return await self.daily(inst)

    async def dividends(self, symbol):
        return [(B.session_date(DAY0 + 400), 1.0)] if symbol == "AAA" else []

    async def latest_prices(self, instruments):
        return {}

    async def macro(self):
        return []


class _NoResearch:
    def latest(self, key):
        return None

    def enqueue(self, key, force=False):
        pass


def _seed(db: Database, rows: list[tuple[str, str, str, str]]) -> None:
    now = datetime.now(UTC)
    for key, seg, sym, isin in rows:
        db.execute(
            "INSERT INTO instruments VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                key,
                seg,
                "NSE",
                "INDEX" if seg == "NSE_INDEX" else "EQ",
                sym,
                sym,
                sym,
                isin,
                "1",
                1,
                0.05,
                "test",
                now,
            ],
        )


def test_analysis_end_to_end_with_synthetic_prices():
    db = Database(":memory:")
    names = ["AAA", "BBB", "CCC", "DDD"]
    _seed(
        db,
        [(f"NSE_EQ|IN{n}", "NSE_EQ", n, f"IN{n}") for n in names]
        + [("NSE_INDEX|Nifty 50", "NSE_INDEX", "NIFTY", "")],
    )
    now = datetime.now(UTC)
    for n, ind in zip(names, ["IT", "Energy", "IT", "Healthcare"], strict=True):
        db.execute(
            "INSERT INTO index_constituents VALUES (?,?,?,?,?,?,?)",
            ["NIFTY 500", n, f"IN{n}", n, ind, "test", now],
        )
    db.execute(
        "INSERT INTO index_constituents VALUES (?,?,?,?,?,?,?)",
        ["NIFTY 100", "DDD", "INDDD", "DDD", "Healthcare", "test", now],
    )
    closes = _closes(_factor_returns(5, 700))
    data = _FakeData(dict(zip([*names, "NIFTY"], closes, strict=True)) | {"CCC": closes[2][:100]})
    watch = ["NSE_EQ|INAAA", "NSE_EQ|INBBB", "NSE_EQ|INCCC"]
    svc = PortfolioService(db, InstrumentService(db, None), data, _NoResearch(), lambda: watch)
    result = asyncio.run(svc.analyse())

    assert [h.symbol for h in result.holdings] == ["AAA", "BBB"]
    assert result.excluded[0].symbol == "CCC" and "sessions of history" in result.excluded[0].reason
    keys = [s.key for s in result.strategies]
    assert keys == ["equal_weight", "inverse_vol", "min_variance", "risk_parity", "research_tilt"]
    for s in result.strategies:
        assert math.isclose(sum(w.weight for w in s.weights), 1.0, abs_tol=1e-3)
        assert (s.backtest is None) == (s.key == "research_tilt")
    bt = result.strategies[0].backtest
    assert bt.stats.days > 300 and bt.benchmark.start == bt.stats.start
    assert result.candidates and result.candidates[0].symbol == "DDD"
    assert result.candidates[0].validation is not None
    assert any("Survivorship" in x for x in result.limitations)
    assert [o.key for o in result.objectives] == ["lower_risk", "balanced", "growth", "income"]
    assert result.benchmark_label == "NIFTY 50 (price index)"
