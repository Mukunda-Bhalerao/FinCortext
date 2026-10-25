import math
import random
from datetime import UTC, date, datetime

from app.agents.base import PriceSeries
from app.schemas.market import Instrument
from app.schemas.plan import Preferences
from app.services.planner import AssetData, build_plan, prepare, preview
from app.tools import backtest as B
from app.tools import portfolio as P
from app.tools.objectives import OBJECTIVES, objective_weights

DAY0 = 19000  # 2022-01-09 IST


def _returns(n_assets: int, days: int, seed: int = 3) -> list[list[float]]:
    rng = random.Random(seed)
    f = [rng.gauss(0.0004, 0.01) for _ in range(days)]
    return [
        [0.5 * f[k] + rng.gauss(0.0003, 0.006 + 0.005 * i) for k in range(days)]
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


def _eq(_w, _t):
    return [0.5, 0.5]


# --- costs and taxes ------------------------------------------------------------------------


def test_cost_rates_itemise_indian_delivery_charges():
    c = B.CostModel()
    fees = (0.0000297 + 0.000001) * 1.18
    assert math.isclose(c.buy_rate, 0.001 + 0.00015 + fees + 0.0005)
    assert math.isclose(c.sell_rate, 0.001 + fees + 0.0005)
    assert math.isclose(
        c.order_cost(100_000, 50_000, 2), 100_000 * c.buy_rate + 50_000 * c.sell_rate + 2 * 15.93
    )


def test_capital_gains_tax_rules():
    tax = B.TaxModel()
    due, carry = B.capital_gains_tax(100_000, 200_000, (0.0, 0.0), tax)
    assert math.isclose(due, 20_000 + 75_000 * 0.125) and carry == (0.0, 0.0)
    # Short-term loss offsets long-term gain; the exemption still applies.
    due, carry = B.capital_gains_tax(-50_000, 200_000, (0.0, 0.0), tax)
    assert math.isclose(due, 25_000 * 0.125) and carry == (0.0, 0.0)
    # A long-term loss cannot offset a short-term gain and carries forward.
    due, carry = B.capital_gains_tax(10_000, -30_000, (0.0, 0.0), tax)
    assert math.isclose(due, 2_000) and carry == (0.0, 30_000)


def test_fiscal_year_turns_in_april():
    mar31 = (date(2024, 3, 31) - P.EPOCH).days - 1
    apr1 = (date(2024, 4, 1) - P.EPOCH).days - 1
    assert B.fiscal_year(mar31) == 2023 and B.fiscal_year(apr1) == 2024


# --- dividends --------------------------------------------------------------------------------


def test_dividends_map_to_sessions_and_reject_implausible_amounts():
    days = [DAY0, DAY0 + 1, DAY0 + 3]  # DAY0 + 2 is a holiday
    closes = [100.0, 100.0, 100.0]
    holiday = B.session_date(DAY0 + 2)
    mapped, skipped = B.map_dividends(
        days, closes, [(holiday, 2.0), (B.session_date(DAY0 + 1), 40.0)]
    )
    assert mapped == {2: 2.0} and skipped == [B.session_date(DAY0 + 1)]


def test_total_return_index_reinvests_dividends():
    tr = B.total_return_index([100.0, 98.0, 99.0], {1: 2.0})
    assert math.isclose(tr[1], 100.0) and math.isclose(tr[2], 100.0 * 99 / 98)


# --- simulation -------------------------------------------------------------------------------


def _setup(n=2, sessions=800, seed=3):
    closes = _closes(_returns(n, sessions, seed))
    days = list(range(DAY0, DAY0 + len(closes[0])))
    return days, closes


def test_simulation_has_no_look_ahead():
    days, closes = _setup(3)
    divs = [{}, {}, {}]

    def fn(W, t):
        return P.risk_parity(P.shrunk_covariance(W)[0])

    base = B.simulate(days, closes, divs, fn)
    schedule = [i for i in P.month_starts(days) if i - 1 >= 252]
    cut = schedule[2]
    altered = [c[: cut + 1] + [x * 1.4 for x in c[cut + 1 :]] for c in closes]
    again = B.simulate(days, altered, divs, fn)
    assert again.weights_history[:3] == base.weights_history[:3]
    assert again.weights_history[3:] != base.weights_history[3:]


def test_simulation_charges_costs_and_pays_dividends():
    days, closes = _setup()
    plain = B.simulate(days, closes, [{}, {}], _eq)
    assert plain.costs > 0 and plain.equity[1] < 1  # buying from cash costs money
    paying = {k: 1.0 for k in range(300, 800, 90)}
    with_div = B.simulate(days, closes, [paying, {}], _eq)
    assert with_div.equity[-1] > plain.equity[-1] and with_div.dividends > 0


def test_after_tax_never_beats_pre_tax():
    days, closes = _setup(seed=9)
    paying = {k: 1.0 for k in range(300, 800, 90)}
    pre = B.simulate(days, closes, [paying, {}], _eq)
    after = B.simulate(days, closes, [paying, {}], _eq, tax=B.TaxModel())
    assert after.taxes > 0 and after.equity[-1] < pre.equity[-1]


def test_bootstrap_is_reproducible_and_ordered():
    rng = random.Random(1)
    excess = [rng.gauss(0.0002, 0.01) for _ in range(600)]
    a, b = B.block_bootstrap(excess), B.block_bootstrap(excess)
    assert a == b and a[0] < a[1] and 0 <= a[2] <= 1


def test_momentum_skips_the_latest_month():
    window = [[0.01] * 231 + [-0.5] * 21]
    assert math.isclose(B.momentum(window)[0], 1.01**231 - 1)


# --- objectives and plans ---------------------------------------------------------------------


def test_objectives_respect_caps_and_lower_risk_is_calmer():
    R = _returns(5, 300)
    S, _ = P.shrunk_covariance(R)
    sectors = ["A", "B", "C", "D", "E"]
    low, _, _ = objective_weights(OBJECTIVES["lower_risk"], S, sectors)
    growth, _, _ = objective_weights(OBJECTIVES["growth"], S, sectors, [-1, -0.5, 0, 0.5, 1])
    assert max(low) <= 0.24 + 1e-9 and max(growth) <= 0.40 + 1e-9
    assert P.port_vol(low, S) < P.port_vol(growth, S)
    assert growth[4] > growth[0]


def _asset(sym: str, closes: list[float], divs=(), sector="IT", role="holding") -> AssetData:
    inst = Instrument(
        instrument_key=f"NSE_EQ|IN{sym}",
        symbol=sym,
        name=sym,
        exchange="NSE",
        segment="NSE_EQ",
        instrument_type="EQ",
        isin=f"IN{sym}",
    )
    times = [(DAY0 + k) * 86400 for k in range(len(closes))]
    series = PriceSeries(sym, times, closes, "test", datetime.now(UTC))
    return AssetData(
        inst, sector, series, list(divs) if divs is not None else None, ("positive", 0.4, 0.8), role
    )


def test_build_plan_end_to_end():
    closes = _closes(_returns(4, 800))
    ex = B.session_date(DAY0 + 500)
    assets = [
        _asset("AAA", closes[0], [(ex, 1.0)], "IT"),
        _asset("BBB", closes[1], None, "Energy"),
        _asset("CCC", closes[2], [], "Healthcare", role="added"),
    ]
    bench = _asset("BENCH", closes[3])
    prep = prepare(assets, bench)
    assert any("Dividends unavailable for BBB" in n for n in prep.notes)
    holdings = {"NSE_EQ|INAAA": (100.0, 90.0)}
    plan = build_plan(prep, Preferences(objective="balanced"), 0.06, holdings)
    assert math.isclose(sum(a.weight for a in plan.assets), 1.0, abs_tol=1e-3)
    bt = plan.backtest
    assert bt is not None and bt.after_tax is not None and bt.uncertainty is not None
    assert bt.pre_tax.start == bt.benchmark.start and bt.years_table
    assert plan.current is not None and plan.current.label == "Your current holdings"
    assert plan.trades is not None and plan.trades.basis == "holdings"
    assert {t.symbol for t in plan.trades.lines} == {"AAA", "BBB", "CCC"}
    assert any(s.key == "rates_2022" and s.covered for s in plan.stress)
    assert plan.explanation and plan.risk.level in ("low", "moderate", "high", "very_high")
    p = preview(prep, "lower_risk", 0.06, 1_000_000, 0.3)
    assert p.volatility is not None and p.cagr is not None


def test_plan_without_holdings_spends_capital():
    closes = _closes(_returns(3, 700))
    prep = prepare(
        [_asset("AAA", closes[0]), _asset("BBB", closes[1], sector="Energy")],
        _asset("B", closes[2]),
    )
    plan = build_plan(prep, Preferences(objective="lower_risk", capital=500_000), 0.0)
    t = plan.trades
    assert t.basis == "capital" and all(x.action in ("buy", "hold") for x in t.lines)
    assert 0 <= t.cash_left < 500_000 * 0.05
