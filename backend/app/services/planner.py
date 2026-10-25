"""Builds a portfolio plan for one objective: weights, risk, a walk-forward backtest with
dividends, costs and taxes, historical stress replays and the trades to get there.

Synchronous and CPU-bound; callers run it in a worker thread. Every number comes from the
price, dividend and research data handed in.
"""

import math
import statistics
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime

from app.agents.base import PriceSeries
from app.schemas.market import Instrument
from app.schemas.plan import (
    Comparison,
    ObjectiveInfo,
    PlanAsset,
    PlanBacktest,
    PortfolioPlan,
    Preferences,
    RiskSummary,
    StressResult,
    TradeLine,
    TradePlan,
    Uncertainty,
    YearReturn,
)
from app.schemas.portfolio import CurvePoint, Excluded, ObjectivePreview, PerfStats
from app.tools import backtest as B
from app.tools import portfolio as P
from app.tools.objectives import OBJECTIVES, Objective, objective_weights

LOOKBACK = P.TRADING_DAYS
MIN_HISTORY = LOOKBACK + 63
CURVE_STEP = 5
COSTS = B.CostModel()

# Market-wide episodes inside the ten-year window, from NIFTY 50 peak to trough.
EPISODES = [
    ("covid_2020", "COVID-19 crash", date(2020, 2, 19), date(2020, 3, 23)),
    ("rates_2022", "2022 rate-hike sell-off", date(2022, 1, 17), date(2022, 6, 17)),
    ("correction_2024", "Late-2024 correction", date(2024, 9, 27), date(2025, 3, 3)),
]


@dataclass
class AssetData:
    inst: Instrument
    sector: str
    series: PriceSeries
    dividends: list[tuple[date, float]] | None  # None: the source was unavailable
    research: tuple[str, float | None, float | None] | None = None  # signal, score, confidence
    role: str = "holding"


@dataclass
class Prepared:
    assets: list[AssetData]
    days: list[int]
    closes: list[list[float]]
    divs: list[dict[int, float]]
    bench: AssetData
    bench_closes: list[float]
    bench_divs: dict[int, float]
    excluded: list[Excluded] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    limited_by: str | None = None


def day_to_date(day: int) -> date:
    return B.session_date(day)


def day_key(d: date) -> int:
    return (d - P.EPOCH).days - 1


def curve(days: Sequence[int], equity: Sequence[float], start: int) -> list[CurvePoint]:
    """``equity[k + 1]`` is the value after session ``start + k`` (``equity[0]`` is cash)."""
    pts = []
    last = min(len(equity) - 1, len(days) - start)
    for k in range(last):
        if k % CURVE_STEP == 0 or k == last - 1:
            pts.append(
                CurvePoint(time=(days[start + k] + 1) * 86400, value=round(equity[k + 1], 5))
            )
    return pts


def perf(daily: Sequence[float], days: Sequence[int], start: int, rf: float) -> PerfStats:
    s = P.stats(daily, rf)
    end = min(start + len(daily) - 1, len(days) - 1)
    return PerfStats(
        cagr=s.cagr,
        volatility=s.volatility,
        sharpe=s.sharpe,
        max_drawdown=s.max_drawdown,
        total_return=s.total_return,
        start=day_to_date(days[start]) if days else None,
        end=day_to_date(days[end]) if days else None,
        days=s.days,
    )


def prepare(assets: list[AssetData], bench: AssetData) -> Prepared:
    usable: list[AssetData] = []
    excluded: list[Excluded] = []
    notes: list[str] = []
    for a in assets:
        if len(a.series.closes) < MIN_HISTORY:
            excluded.append(
                Excluded(
                    symbol=a.inst.symbol,
                    reason=f"{len(a.series.closes)} sessions of history; {MIN_HISTORY} needed.",
                )
            )
        elif (jump := P.suspicious_jump(a.series.closes)) is not None:
            excluded.append(
                Excluded(
                    symbol=a.inst.symbol,
                    reason=f"One-day move of {jump:+.0%} suggests an unadjusted corporate action; "
                    "excluded to avoid a false return.",
                )
            )
        else:
            usable.append(a)
    days, aligned = P.align(
        {a.inst.instrument_key: a.series.pairs for a in usable} | {"__bench": bench.series.pairs}
    )
    closes = [aligned[a.inst.instrument_key] for a in usable]
    divs = []
    for a, c in zip(usable, closes, strict=True):
        if a.dividends is None:
            notes.append(f"Dividends unavailable for {a.inst.symbol}; its returns are price only.")
            divs.append({})
            continue
        mapped, skipped = B.map_dividends(days, c, a.dividends)
        if skipped:
            notes.append(
                f"{len(skipped)} implausible dividend record(s) for {a.inst.symbol} ignored."
            )
        divs.append(mapped)
    bench_closes = aligned.get("__bench", [])
    bench_divs = B.map_dividends(days, bench_closes, bench.dividends or [])[0] if days else {}
    limited_by = None
    if usable and days:
        firsts = [(a.series.times[0] // 86400, a.inst.symbol) for a in usable]
        latest_first = max(firsts)
        if latest_first[0] - min(f for f, _ in firsts) > 60:
            limited_by = (
                f"History starts {day_to_date(days[0]):%b %Y} because {latest_first[1]} has "
                "prices only from then."
            )
    return Prepared(
        usable, days, closes, divs, bench, bench_closes, bench_divs, excluded, notes, limited_by
    )


def _level(ratio: float) -> tuple[str, str]:
    if ratio < 0.85:
        return "low", "calmer than the NIFTY 50"
    if ratio < 1.15:
        return "moderate", "about as volatile as the NIFTY 50"
    if ratio < 1.5:
        return "high", f"about {ratio:.1f}x the swings of the NIFTY 50"
    return "very_high", f"about {ratio:.1f}x the swings of the NIFTY 50"


def _signals(obj: Objective, window, prep: Prepared, t: int) -> list[float] | None:
    if obj.tilt == "momentum":
        return B.cross_section_scores(B.momentum(window))
    if obj.tilt == "yield":
        return B.cross_section_scores(
            [B.trailing_yield(c, d, t) for c, d in zip(prep.closes, prep.divs, strict=True)]
        )
    return None


def _shrunk(R: list[list[float]]) -> P.Matrix:
    return P.shrunk_covariance(R)[0]


def weight_fn(obj: Objective, prep: Prepared, max_weight: float | None):
    sectors = [a.sector for a in prep.assets]

    def fn(window: list[list[float]], t: int) -> list[float]:
        S = _shrunk(window)
        return objective_weights(obj, S, sectors, _signals(obj, window, prep, t), None, max_weight)[
            0
        ]

    return fn


def bench_run(prep: Prepared, start: int) -> list[float]:
    """Buy-and-hold benchmark from cash at the close of ``start``, one purchase cost."""
    tr = B.total_return_index(prep.bench_closes, prep.bench_divs)
    daily = [-COSTS.buy_rate]
    for t in range(start + 1, len(tr)):
        daily.append(tr[t] / tr[t - 1] - 1)
    return daily


def equity(daily: Sequence[float]) -> list[float]:
    eq = [1.0]
    for r in daily:
        eq.append(eq[-1] * (1 + r))
    return eq


@dataclass
class _Run:
    pre: B.Simulation
    after: B.Simulation | None


def _simulate(prep: Prepared, fn, capital: float, slab: float, with_tax: bool) -> _Run | None:
    pre = B.simulate(prep.days, prep.closes, prep.divs, fn, LOOKBACK, COSTS, capital)
    if pre is None:
        return None
    after = None
    if with_tax:
        after = B.simulate(
            prep.days,
            prep.closes,
            prep.divs,
            fn,
            LOOKBACK,
            COSTS,
            capital,
            B.TaxModel(dividend_rate=slab),
        )
    return _Run(pre, after)


def _stress(prep: Prepared, weights: list[float]) -> list[StressResult]:
    """Today's weights replayed over past episodes on each stock's own total-return history."""

    def tr_map(a: AssetData) -> dict[int, float]:
        days = [t // 86400 for t in a.series.times]
        mapped, _ = B.map_dividends(days, a.series.closes, a.dividends or [])
        return dict(zip(days, B.total_return_index(a.series.closes, mapped), strict=True))

    maps = [tr_map(a) for a in prep.assets]
    bench = tr_map(prep.bench)
    bench_days = sorted(bench)
    out: list[StressResult] = []

    def replay(key: str, name: str, kind: str, a_day: int, b_day: int) -> StressResult | None:
        window = [d for d in bench_days if a_day <= d <= b_day]
        if len(window) < 5:
            return None
        start_d, end_d = day_to_date(window[0]), day_to_date(window[-1])
        bench_ret = bench[window[-1]] / bench[window[0]] - 1
        missing = [
            a.inst.symbol for a, m in zip(prep.assets, maps, strict=True) if window[0] not in m
        ]
        if missing:
            return StressResult(
                key=key,
                name=name,
                kind=kind,  # type: ignore[arg-type]
                start=start_d,
                end=end_d,
                portfolio=None,
                portfolio_drawdown=None,
                benchmark=bench_ret,
                covered=False,
                note=f"No prices then for {', '.join(missing)}.",
            )
        series = []
        for m in maps:
            last = m[window[0]]
            path = []
            for d in window:
                last = m.get(d, last)
                path.append(last)
            series.append(path)
        ret, dd = B.hold_return(series, weights, 0, len(window) - 1)
        return StressResult(
            key=key,
            name=name,
            kind=kind,  # type: ignore[arg-type]
            start=start_d,
            end=end_d,
            portfolio=ret,
            portfolio_drawdown=dd,
            benchmark=bench_ret,
            covered=True,
        )

    for key, name, a, b in EPISODES:
        r = replay(key, name, "episode", day_key(a), day_key(b))
        if r:
            out.append(r)
    closes = [bench[d] for d in bench_days]
    worst = B.worst_window(closes, 21)
    if worst:
        a, b, _ = worst
        r = replay(
            "worst_month",
            "Worst month for the NIFTY 50 in the data",
            "worst_month",
            bench_days[a],
            bench_days[b],
        )
        if r and not any(r.start == x.start for x in out):
            out.append(r)
    return out


def _trades(
    prep: Prepared,
    weights: list[float],
    prefs: Preferences,
    holdings: dict[str, tuple[float, float | None]],
    prices: dict[str, tuple[float, str]],
    others: dict[str, tuple[str, float]],
) -> TradePlan:
    """``others``: held instruments outside the plan, key -> (symbol, price)."""
    price_of = {
        a.inst.instrument_key: prices.get(a.inst.instrument_key, (c[-1], "last close"))[0]
        for a, c in zip(prep.assets, prep.closes, strict=True)
    }
    rows = [
        (a.inst.instrument_key, a.inst.symbol, w, price_of[a.inst.instrument_key])
        for a, w in zip(prep.assets, weights, strict=True)
    ] + [(k, sym, 0.0, px) for k, (sym, px) in others.items()]
    held = {k: q for k, (q, _) in holdings.items() if q > 0}
    basis = "holdings" if held else "capital"
    total = sum(held.get(k, 0.0) * px for k, _, _, px in rows) if held else prefs.capital
    lines: list[TradeLine] = []
    buys = sells = 0.0
    orders = 0
    gain = 0.0
    has_cost = False
    spent = 0.0
    # Buying from cash leaves room for the purchase charges.
    budget = total if held else total * (1 - COSTS.buy_rate)
    for k, sym, w, px in rows:
        qty = held.get(k, 0.0)
        cur = qty * px
        target = w * budget
        delta = target - cur
        dq = int(delta / px) if px > 0 else 0
        if dq < 0:
            dq = max(dq, -int(math.ceil(qty)))
        small = abs(dq * px) < 0.005 * total
        action = "hold" if dq == 0 or small else ("buy" if dq > 0 else "sell")
        if action == "hold":
            dq = 0
        if action == "buy":
            buys += dq * px
        elif action == "sell":
            sells += -dq * px
            orders += 1
            cost = holdings.get(k, (0.0, None))[1]
            if cost is not None:
                has_cost = True
                gain += -dq * (px - cost)
        spent += (qty + dq) * px
        lines.append(
            TradeLine(
                symbol=sym,
                instrument_key=k,
                price=px,
                current_qty=qty,
                current_value=cur,
                current_weight=cur / total if total else 0.0,
                target_weight=w,
                target_value=target,
                delta_value=dq * px,
                delta_qty=dq,
                action=action,  # type: ignore[arg-type]
            )
        )
    est = COSTS.order_cost(buys, sells, orders)
    note = (
        "Whole shares at the latest price; small changes under 0.5% of the portfolio are left "
        "alone to save costs."
    )
    if basis == "holdings" and sells and not has_cost:
        note += " Add average costs to see the gain realised by the sales."
    return TradePlan(
        basis=basis,  # type: ignore[arg-type]
        total_value=total,
        lines=lines,
        est_costs=est,
        cash_left=total - spent - est if basis == "capital" else 0.0,
        realised_gain=gain if has_cost else None,
        note=note,
    )


def _explain(
    obj: Objective,
    prep: Prepared,
    weights: list[float],
    vols: list[float],
    mom: list[float],
    yields: list[float],
    overlay: list[float | None] | None,
) -> list[str]:
    syms = [a.inst.symbol for a in prep.assets]
    n = len(syms)
    if n == 0:
        return []
    order = sorted(range(n), key=lambda i: -weights[i])
    top, low = order[0], order[-1]
    out = []
    if n == 1:
        return [f"{syms[0]} is the only stock with enough clean history, so it holds 100%."]
    if obj.base == "min_variance":
        out.append(
            f"{syms[top]} gets the largest weight ({weights[top]:.0%}): with "
            f"{vols[top]:.0%} volatility it does the most to keep swings down given how the "
            "stocks move together."
        )
    elif obj.base == "risk_parity":
        out.append(
            f"Riskier stocks get less money so each carries a similar share of risk: "
            f"{syms[top]} ({vols[top]:.0%} volatility) gets {weights[top]:.0%}, "
            f"{syms[low]} ({vols[low]:.0%}) gets {weights[low]:.0%}."
        )
    else:
        out.append("Starts from equal weights, then tilts toward stronger price trends.")
    if obj.tilt == "momentum":
        hi = max(range(n), key=lambda i: mom[i])
        lo = min(range(n), key=lambda i: mom[i])
        if hi != lo:
            out.append(
                f"Momentum tilt: {syms[hi]} returned {mom[hi]:+.0%} over the 11 months before "
                f"the latest month and gets more; {syms[lo]} ({mom[lo]:+.0%}) gets less."
            )
    if obj.tilt == "yield":
        hi = max(range(n), key=lambda i: yields[i])
        lo = min(range(n), key=lambda i: yields[i])
        if hi != lo:
            out.append(
                f"Income tilt: {syms[hi]} paid {yields[hi]:.1%} of its price in dividends over "
                f"the last year and gets more; {syms[lo]} ({yields[lo]:.1%}) gets less."
            )
    sectors: dict[str, float] = {}
    for a, x in zip(prep.assets, weights, strict=True):
        sectors[a.sector] = sectors.get(a.sector, 0.0) + x
    if len(sectors) >= 3:
        for sec, total in sectors.items():
            members = [a.inst.symbol for a in prep.assets if a.sector == sec]
            if len(members) > 1 and total >= obj.sector_cap - 1e-3:
                out.append(
                    f"The {obj.sector_cap:.0%} sector cap holds {' and '.join(members)} ({sec}) to "
                    f"{total:.0%} together, so their share of risk ends up smaller."
                )
    if overlay and any(x is not None for x in overlay):
        moved = [(i, x) for i, x in enumerate(overlay) if x is not None and abs(x) >= 0.05]
        if moved:
            i, x = max(moved, key=lambda p: abs(p[1]))
            verb = "raised" if x > 0 else "lowered"
            out.append(
                f"Research overlay {verb} {syms[i]}'s weight (composite score x confidence "
                f"{x:+.2f}). This applies to today's weights only; the backtest cannot use it."
            )
    return out


def build_plan(
    prep: Prepared,
    prefs: Preferences,
    rf: float,
    holdings: dict[str, tuple[float, float | None]] | None = None,
    prices: dict[str, tuple[float, str]] | None = None,
    others: dict[str, tuple[str, float]] | None = None,
    bench_label: str = "NIFTY 50",
    light: bool = False,
) -> PortfolioPlan:
    started = time.perf_counter()
    obj = OBJECTIVES[prefs.objective]
    holdings = holdings or {}
    prices = prices or {}
    info = ObjectiveInfo(
        key=obj.key,  # type: ignore[arg-type]
        label=obj.label,
        tagline=obj.tagline,
        method=obj.method,
    )
    assumptions = [
        f"Costs per trade: buy {COSTS.buy_rate:.3%}, sell {COSTS.sell_rate:.3%} of value plus "
        f"Rs {COSTS.dp_per_sell:.2f} per stock sold (STT, stamp duty, exchange, SEBI and GST at "
        "2025 rates, zero brokerage, 0.05% assumed slippage).",
        "Rebalanced at the close of the first session of each month using only the year of "
        "data before that day. Fractional shares; dividends reinvested at the next rebalance.",
        f"After-tax: 20% on gains held up to 12 months, 12.5% above Rs 1.25 lakh a year after "
        f"that, dividends taxed at {prefs.tax_slab:.0%}; tax paid each April. Gains not yet "
        "sold at the end are not taxed.",
    ]
    limitations = [
        "Stocks are chosen today, so the history flatters them (survivorship and selection "
        "bias). Compare objectives with each other and with the benchmark, not with what you "
        "would have earned.",
        "Past behaviour, not a forecast. Volatility and correlations change, especially in crises.",
    ] + prep.notes
    n = len(prep.assets)
    base = PortfolioPlan(
        preferences=prefs,
        objective=info,
        computed_at=datetime.now(UTC),
        as_of=day_to_date(prep.days[-1]) if prep.days else None,
        assets=[],
        excluded=prep.excluded,
        risk=None,
        backtest=None,
        backtest_note=None,
        stress=[],
        trades=None,
        current=None,
        explanation=[],
        weight_note=None,
        assumptions=assumptions,
        limitations=limitations,
        duration_ms=0,
    )
    if n == 0 or len(prep.days) <= LOOKBACK + 1:
        base.backtest_note = "Add stocks with at least 15 months of clean price history."
        base.duration_ms = int((time.perf_counter() - started) * 1000)
        return base

    tr = [B.total_return_index(c, d) for c, d in zip(prep.closes, prep.divs, strict=True)]
    R = [P.simple_returns(x)[-LOOKBACK:] for x in tr]
    S = _shrunk(R)
    sectors = [a.sector for a in prep.assets]
    t_now = len(prep.days)
    mom = B.momentum(R)
    yields = [B.trailing_yield(c, d, t_now) for c, d in zip(prep.closes, prep.divs, strict=True)]
    overlay = None
    if prefs.research_overlay:
        overlay = [
            (a.research[1] * a.research[2])
            if a.research and a.research[1] is not None and a.research[2] is not None
            else None
            for a in prep.assets
        ]
    w, _, note = objective_weights(
        obj, S, sectors, _signals(obj, R, prep, t_now), overlay, prefs.max_weight
    )
    vols = [math.sqrt(max(S[i][i], 0.0) * P.TRADING_DAYS) for i in range(n)]
    rc = P.risk_contributions(w, S)
    corr = P.correlation(S)
    off = [corr[i][j] for i in range(n) for j in range(n) if i < j]
    bench_tr = B.total_return_index(prep.bench_closes, prep.bench_divs)
    bench_R = P.simple_returns(bench_tr)[-LOOKBACK:]
    bench_vol = P.stats(bench_R).volatility
    vol = P.port_vol(w, S)
    dr = P.diversification_ratio(w, S)
    level, level_text = _level(vol / bench_vol) if bench_vol else ("moderate", "")
    sector_w: dict[str, float] = {}
    for sec, x in zip(sectors, w, strict=True):
        sector_w[sec] = round(sector_w.get(sec, 0.0) + x, 4)
    top_risk = max(range(n), key=lambda i: rc[i])
    top_w = max(range(n), key=lambda i: w[i])
    base.risk = RiskSummary(
        volatility=vol,
        benchmark_volatility=bench_vol,
        level=level,  # type: ignore[arg-type]
        level_text=level_text,
        diversification_ratio=dr,
        diversification_score=int(round(min(100.0, max(0.0, (1 - 1 / dr) / 0.6 * 100)))),
        effective_n=P.effective_n(w),
        top_risk_symbol=prep.assets[top_risk].inst.symbol,
        top_risk_share=rc[top_risk],
        largest_weight_symbol=prep.assets[top_w].inst.symbol,
        largest_weight=w[top_w],
        sector_weights=sector_w,
        avg_correlation=statistics.fmean(off) if off else None,
    )
    base.assets = [
        PlanAsset(
            symbol=a.inst.symbol,
            name=a.inst.name,
            instrument_key=a.inst.instrument_key,
            sector=a.sector,
            role=a.role,  # type: ignore[arg-type]
            weight=round(w[i], 4),
            risk_share=round(rc[i], 4),
            volatility=vols[i],
            momentum=mom[i],
            dividend_yield=yields[i] if a.dividends is not None else None,
            research_signal=a.research[0] if a.research else None,
            research_score=a.research[1] if a.research else None,
            research_confidence=a.research[2] if a.research else None,
            price=prices.get(a.inst.instrument_key, (prep.closes[i][-1], "last close"))[0],
            price_basis=prices.get(a.inst.instrument_key, (0.0, "last close"))[1],
        )
        for i, a in enumerate(prep.assets)
    ]
    base.weight_note = note
    base.explanation = _explain(obj, prep, w, vols, mom, yields, overlay)

    # Baseline: current holdings by value, otherwise equal weight of the watchlist stocks.
    held_value = [
        holdings.get(a.inst.instrument_key, (0.0, None))[0] * prep.closes[i][-1]
        for i, a in enumerate(prep.assets)
    ]
    if sum(held_value) > 0:
        bw = [v / sum(held_value) for v in held_value]
        baseline_label = "Your current holdings"
    else:
        mask = [1.0 if a.role == "holding" else 0.0 for a in prep.assets]
        bw = [m / sum(mask) for m in mask] if sum(mask) else P.equal_weight(S)
        baseline_label = "Equal weight of your watchlist"

    fn = weight_fn(obj, prep, prefs.max_weight)
    run = _simulate(prep, fn, prefs.capital, prefs.tax_slab, with_tax=True)
    base_run = None
    if run is not None and not light:
        base_run = B.simulate(
            prep.days, prep.closes, prep.divs, lambda W, t: bw, LOOKBACK, COSTS, prefs.capital
        )
    base.current = Comparison(
        label=baseline_label,
        volatility=P.port_vol(bw, S),
        diversification_ratio=P.diversification_ratio(bw, S),
        cagr=P.stats(base_run.daily).cagr if base_run else None,
        max_drawdown=P.max_drawdown(base_run.equity) if base_run else None,
    )
    if run is None:
        base.backtest_note = "Not enough shared history for a walk-forward test."
    else:
        pre, after = run.pre, run.after
        start = pre.start_index
        bench_daily = bench_run(prep, start)
        years = len(pre.daily) / P.TRADING_DAYS or 1.0
        excess = [a - b for a, b in zip(pre.daily, bench_daily, strict=False)]
        boot = None if light else B.block_bootstrap(excess)
        cal = B.calendar_returns(prep.days, pre.daily, start)
        bcal = {y: r for y, r, _ in B.calendar_returns(prep.days, bench_daily, start)}
        divs_note = (
            "Total return: dividends from Yahoo Finance reinvested."
            if not any("Dividends unavailable" in x for x in prep.notes)
            else "Total return where dividends were available; see limitations."
        )
        base.backtest = PlanBacktest(
            start=day_to_date(prep.days[start]),
            end=day_to_date(prep.days[-1]),
            years=years,
            limited_by=prep.limited_by,
            pre_tax=perf(pre.daily, prep.days, start, rf),
            after_tax=perf(after.daily, prep.days, start, rf) if after else None,
            benchmark=perf(bench_daily, prep.days, start, rf),
            benchmark_label=bench_label,
            baseline=perf(base_run.daily, prep.days, start, rf) if base_run else None,
            baseline_label=baseline_label if base_run else None,
            curve=curve(prep.days, pre.equity, start),
            after_tax_curve=curve(prep.days, after.equity, start) if after else [],
            benchmark_curve=curve(prep.days, equity(bench_daily), start),
            baseline_curve=curve(prep.days, base_run.equity, start) if base_run else [],
            costs_per_year=pre.costs / years,
            taxes_per_year=after.taxes / years if after else None,
            dividends_per_year=pre.dividends / years,
            turnover_per_year=pre.turnover / years,
            rebalances=pre.rebalances,
            years_table=[
                YearReturn(year=y, portfolio=r, benchmark=bcal.get(y), partial=c < 200)
                for y, r, c in cal
            ],
            uncertainty=Uncertainty(
                excess_low=boot[0],
                excess_high=boot[1],
                prob_outperform=boot[2],
                method="Moving-block bootstrap of daily returns over the benchmark (21-session "
                "blocks, 400 resamples, fixed seed).",
            )
            if boot
            else None,
            return_basis=divs_note,
        )
    if not light:
        base.stress = _stress(prep, w)
        base.trades = _trades(prep, w, prefs, holdings, prices, others or {})
    base.duration_ms = int((time.perf_counter() - started) * 1000)
    return base


def preview(prep: Prepared, key: str, rf: float, capital: float, slab: float) -> ObjectivePreview:
    obj = OBJECTIVES[key]
    plan = build_plan(
        prep,
        Preferences(objective=key, capital=capital, tax_slab=slab, research_overlay=False),  # type: ignore[arg-type]
        rf,
        light=True,
    )
    bt = plan.backtest
    return ObjectivePreview(
        key=obj.key,  # type: ignore[arg-type]
        label=obj.label,
        tagline=obj.tagline,
        volatility=plan.risk.volatility if plan.risk else None,
        cagr=bt.pre_tax.cagr if bt else None,
        after_tax_cagr=bt.after_tax.cagr if bt and bt.after_tax else None,
        max_drawdown=bt.pre_tax.max_drawdown if bt else None,
        top_weight_symbol=plan.risk.largest_weight_symbol if plan.risk else None,
        top_weight=plan.risk.largest_weight if plan.risk else None,
    )
