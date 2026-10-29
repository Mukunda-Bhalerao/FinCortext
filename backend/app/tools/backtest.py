"""Backtesting V2: a money-based simulation with dividends, Indian trading costs and capital
gains tax. Pure Python, no I/O.

Conventions follow ``tools.portfolio``: ``days`` are UTC day numbers of the candle start (IST
date = day + 1), ``closes[i]`` are split- and bonus-adjusted closes on those sessions, and
``divs[i]`` maps a session index to the cash dividend per share going ex on that session.

Look-ahead protection: on a rebalance session ``t`` the weight function sees returns of
sessions ``t - lookback .. t - 1`` only and trades at the close of ``t``.
"""

import math
import random
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta

from app.tools.portfolio import EPOCH, TRADING_DAYS, max_drawdown, month_starts, simple_returns

# --- costs and taxes -------------------------------------------------------------------------


@dataclass(frozen=True)
class CostModel:
    """Equity delivery charges on NSE, as fractions of value traded unless noted.

    Defaults follow the published 2025 schedules (STT, stamp duty, NSE transaction charge,
    SEBI fee, GST) for a zero-brokerage discount broker. Slippage stands in for the bid-ask
    spread and market impact of a large-cap order and is an assumption, not a measurement.
    """

    brokerage: float = 0.0
    stt: float = 0.001  # buy and sell, delivery
    stamp_buy: float = 0.00015
    exchange: float = 0.0000297
    sebi: float = 0.000001
    gst: float = 0.18  # on brokerage, exchange and SEBI charges
    slippage: float = 0.0005
    dp_per_sell: float = 15.93  # INR per stock sold, depository charge incl. GST

    @property
    def buy_rate(self) -> float:
        fees = self.brokerage + self.exchange + self.sebi
        return fees * (1 + self.gst) + self.stt + self.stamp_buy + self.slippage

    @property
    def sell_rate(self) -> float:
        fees = self.brokerage + self.exchange + self.sebi
        return fees * (1 + self.gst) + self.stt + self.slippage

    def order_cost(self, buys: float, sells: float, sell_orders: int) -> float:
        return buys * self.buy_rate + sells * self.sell_rate + sell_orders * self.dp_per_sell


@dataclass(frozen=True)
class TaxModel:
    """Listed equity, resident individual, rules for transfers after 23 July 2024."""

    stcg: float = 0.20  # held 12 months or less
    ltcg: float = 0.125
    ltcg_exemption: float = 125_000.0  # INR per financial year
    dividend_rate: float = 0.30  # dividends are taxed at the investor's income-tax slab
    long_term_days: int = 365


def capital_gains_tax(
    st: float, lt: float, carry: tuple[float, float], tax: TaxModel
) -> tuple[float, tuple[float, float]]:
    """Tax due for one financial year and the losses carried forward (short, long).

    Short-term losses offset short- and long-term gains; long-term losses offset long-term
    gains only. Unused losses carry forward (the eight-year limit is not modelled).
    """
    st_loss, st = max(-st, 0.0), max(st, 0.0)
    lt_loss, lt = max(-lt, 0.0), max(lt, 0.0)
    use = min(st_loss, lt)
    lt, st_loss = lt - use, st_loss - use
    c_st, c_lt = carry
    use = min(c_st, st)
    st, c_st = st - use, c_st - use
    use = min(c_st, lt)
    lt, c_st = lt - use, c_st - use
    use = min(c_lt, lt)
    lt, c_lt = lt - use, c_lt - use
    due = st * tax.stcg + max(0.0, lt - tax.ltcg_exemption) * tax.ltcg
    return due, (c_st + st_loss, c_lt + lt_loss)


def session_date(day: int) -> date:
    return EPOCH + timedelta(days=day + 1)


def fiscal_year(day: int) -> int:
    d = session_date(day)
    return d.year if d.month >= 4 else d.year - 1


# --- dividends and total returns -----------------------------------------------------------


def map_dividends(
    days: Sequence[int], closes: Sequence[float], events: Sequence[tuple[date, float]]
) -> tuple[dict[int, float], list[date]]:
    """Session index -> dividend per share. Returns (mapping, implausible ex-dates skipped).

    An ex-date that is not a session moves to the next session. A dividend above 25% of the
    previous close is treated as a data error rather than a payout.
    """
    out: dict[int, float] = {}
    skipped: list[date] = []
    index = {d: i for i, d in enumerate(days)}
    for ex, amount in events:
        key = (ex - EPOCH).days - 1
        i = index.get(key)
        if i is None:
            later = [k for k in range(len(days)) if days[k] > key]
            i = later[0] if later else None
        if i is None or i == 0:
            continue
        if amount > 0.25 * closes[i - 1]:
            skipped.append(ex)
            continue
        out[i] = out.get(i, 0.0) + amount
    return out, skipped


def total_return_index(closes: Sequence[float], divs: dict[int, float]) -> list[float]:
    """Price index with dividends reinvested at the ex-date close (before tax)."""
    if not closes:
        return []
    tr = [closes[0]]
    for t in range(1, len(closes)):
        tr.append(tr[-1] * (closes[t] + divs.get(t, 0.0)) / closes[t - 1])
    return tr


# --- point-in-time signals ---------------------------------------------------------------


def momentum(window: Sequence[Sequence[float]], skip: int = 21) -> list[float]:
    """Cumulative return over the window excluding its last ``skip`` sessions (12-1 momentum)."""
    out = []
    for r in window:
        g = 1.0
        for x in r[: max(0, len(r) - skip)]:
            g *= 1 + x
        out.append(g - 1)
    return out


def trailing_yield(
    closes: Sequence[float], divs: dict[int, float], t: int, sessions: int = TRADING_DAYS
) -> float:
    """Dividends with ex-dates in the ``sessions`` before ``t``, over the close before ``t``."""
    paid = sum(a for i, a in divs.items() if t - sessions <= i < t)
    return paid / closes[t - 1] if t >= 1 and closes[t - 1] > 0 else 0.0


def cross_section_scores(values: Sequence[float]) -> list[float]:
    """Z-scores across assets, halved and clipped to [-1, 1]; all zero when values are equal."""
    n = len(values)
    if n < 2:
        return [0.0] * n
    mean = sum(values) / n
    sd = math.sqrt(sum((v - mean) ** 2 for v in values) / n)
    if sd < 1e-12:
        return [0.0] * n
    return [max(-1.0, min(1.0, (v - mean) / sd / 2)) for v in values]


# --- simulation -------------------------------------------------------------------------------

WeightFn = Callable[[list[list[float]], int], list[float]]


@dataclass
class Simulation:
    start_index: int
    daily: list[float]
    equity: list[float]  # value / starting capital, one point per session from start
    rebalances: int
    turnover: float  # one-way, fraction of value, summed over rebalances
    costs: float  # fraction of then-current value, summed
    taxes: float  # capital gains and dividend tax, fraction of then-current value, summed
    dividends: float  # dividend cash received, fraction of then-current value, summed
    weights_history: list[list[float]] = field(default_factory=list)


def simulate(
    days: Sequence[int],
    closes: Sequence[Sequence[float]],
    divs: Sequence[dict[int, float]],
    weight_fn: WeightFn,
    lookback: int = TRADING_DAYS,
    costs: CostModel | None = None,
    capital: float = 1_000_000.0,
    tax: TaxModel | None = None,
    end: int | None = None,
    start_at: int | None = None,
) -> Simulation | None:
    """Monthly rebalanced, long-only, fractional shares, starting from cash.

    Dividends are paid in cash on the ex-date (after dividend tax when ``tax`` is set) and
    reinvested at the next rebalance. With ``tax``, capital gains are computed per FIFO lot
    and the tax for each financial year is paid on its first session after March; selling to
    pay that tax is not itself taxed. Gains still unrealised at the end are not taxed.
    """
    costs = costs or CostModel()
    end = len(days) if end is None else end
    n = len(closes)
    tr = [total_return_index(c[:end], d) for c, d in zip(closes, divs, strict=True)]
    R = [simple_returns(x) for x in tr]  # R[i][k] is the total return into session k + 1
    schedule = [i for i in month_starts(days[:end]) if i - 1 >= lookback]
    if start_at is not None:
        schedule = [i for i in schedule if i >= start_at]
    if not schedule:
        return None
    start = schedule[0]
    rebalance = set(schedule)
    units = [0.0] * n
    lots: list[list[list[float]]] = [[] for _ in range(n)]  # [session index, units, unit cost]
    cash = capital
    prev_value = capital
    daily: list[float] = []
    equity = [1.0]
    history: list[list[float]] = []
    turnover = cost_frac = tax_frac = div_frac = 0.0
    gains_st = gains_lt = 0.0
    carry = (0.0, 0.0)
    year = fiscal_year(days[start])

    for t in range(start, end):
        price = [closes[i][t] for i in range(n)]

        def value() -> float:
            return cash + sum(units[i] * price[i] for i in range(n))  # noqa: B023

        if t > start:
            for i in range(n):
                d = divs[i].get(t)
                if d and units[i] > 0:
                    amount = units[i] * d
                    v = value()
                    div_frac += amount / v if v > 0 else 0.0
                    if tax:
                        tax_frac += amount * tax.dividend_rate / v if v > 0 else 0.0
                        amount *= 1 - tax.dividend_rate
                    cash += amount

        if tax and fiscal_year(days[t]) != year:
            due, carry = capital_gains_tax(gains_st, gains_lt, carry, tax)
            gains_st = gains_lt = 0.0
            year = fiscal_year(days[t])
            v = value()
            if due > 0 and v > 0:
                tax_frac += due / v
                from_cash = min(cash, due)
                cash -= from_cash
                rest = due - from_cash
                held = sum(units[i] * price[i] for i in range(n))
                if rest > 0 and held > 0:
                    keep = max(0.0, 1 - rest / held)
                    units = [u * keep for u in units]
                    for book in lots:
                        for lot in book:
                            lot[1] *= keep

        if t in rebalance:
            window = [R[i][t - 1 - lookback : t - 1] for i in range(n)]
            target = weight_fn(window, t)
            v = value()
            cost = 0.0
            delta = [0.0] * n
            for _ in range(3):  # post-trade weights match the target net of costs
                investable = v - cost
                delta = [target[i] * investable - units[i] * price[i] for i in range(n)]
                buys = sum(x for x in delta if x > 0)
                sells = -sum(x for x in delta if x < 0)
                orders = sum(1 for x in delta if x < -1e-6)
                cost = costs.order_cost(buys, sells, orders)
            for i in range(n):
                if delta[i] < -1e-9:
                    q = -delta[i] / price[i]
                    book = lots[i]
                    while q > 1e-12 and book:
                        lot = book[0]
                        take = min(q, lot[1])
                        gain = take * (price[i] - lot[2])
                        held_days = days[t] - days[int(lot[0])]
                        if tax and held_days > tax.long_term_days:
                            gains_lt += gain
                        else:
                            gains_st += gain
                        lot[1] -= take
                        q -= take
                        if lot[1] <= 1e-12:
                            book.pop(0)
                    units[i] = max(0.0, units[i] + delta[i] / price[i])
                elif delta[i] > 1e-9:
                    q = delta[i] / price[i]
                    units[i] += q
                    lots[i].append([float(t), q, price[i]])
            invested = sum(units[i] * price[i] for i in range(n))
            cash = v - cost - invested
            traded = buys + sells
            turnover += traded / v / (1 if t == start else 2)
            cost_frac += cost / v
            history.append(list(target))

        now = value()
        daily.append(now / prev_value - 1)
        equity.append(now / capital)
        prev_value = now

    return Simulation(
        start_index=start,
        daily=daily,
        equity=equity,
        rebalances=len(history),
        turnover=turnover,
        costs=cost_frac,
        taxes=tax_frac,
        dividends=div_frac,
        weights_history=history,
    )


# --- statistics ------------------------------------------------------------------------


def calendar_returns(
    days: Sequence[int], daily: Sequence[float], start: int
) -> list[tuple[int, float, int]]:
    """(calendar year, compounded return, sessions) for the sessions covered by ``daily``."""
    out: dict[int, list[float]] = {}
    for k, r in enumerate(daily):
        idx = start + k
        if idx >= len(days):
            break
        y = session_date(days[idx]).year
        g = out.setdefault(y, [1.0, 0])
        g[0] *= 1 + r
        g[1] += 1
    return [(y, g - 1, int(c)) for y, (g, c) in sorted(out.items())]


def block_bootstrap(
    excess: Sequence[float], block: int = 21, samples: int = 400, seed: int = 11
) -> tuple[float, float, float] | None:
    """5th and 95th percentile of the annualised mean daily excess return, and the share of
    resamples above zero. Moving blocks keep short-range dependence; the seed is fixed so the
    result is reproducible."""
    n = len(excess)
    if n < block * 4:
        return None
    rng = random.Random(seed)
    means = []
    starts = n - block + 1
    for _ in range(samples):
        total = 0.0
        count = 0
        while count < n:
            s = rng.randrange(starts)
            seg = excess[s : s + min(block, n - count)]
            total += sum(seg)
            count += len(seg)
        means.append(total / n * TRADING_DAYS)
    means.sort()
    lo = means[int(0.05 * (samples - 1))]
    hi = means[int(0.95 * (samples - 1))]
    return lo, hi, sum(1 for m in means if m > 0) / samples


def percentile_of(value: float, population: Sequence[float]) -> float:
    """Share of the population at or below ``value``."""
    if not population:
        return math.nan
    return sum(1 for p in population if p <= value) / len(population)


def hold_return(
    closes: Sequence[Sequence[float]], weights: Sequence[float], a: int, b: int
) -> tuple[float, float]:
    """Buy-and-hold return and worst drawdown from session ``a`` to ``b`` with fixed starting
    weights (the weights then drift with prices)."""
    path = []
    for t in range(a, b + 1):
        path.append(sum(w * c[t] / c[a] for w, c in zip(weights, closes, strict=True)))
    return path[-1] - 1, max_drawdown(path)


def worst_window(closes: Sequence[float], length: int = 21) -> tuple[int, int, float] | None:
    """Start, end and return of the worst ``length``-session window."""
    if len(closes) <= length:
        return None
    best = None
    for a in range(len(closes) - length):
        r = closes[a + length] / closes[a] - 1
        if best is None or r < best[2]:
            best = (a, a + length, r)
    return best


def equal_weight_cagr(
    closes: Sequence[Sequence[float]], days: Sequence[int], lookback: int, cost_rate: float
) -> float | None:
    """CAGR of an equal-weight, monthly rebalanced portfolio on price returns, charged
    ``cost_rate`` per unit traded. A fast path for comparing many random portfolios."""
    schedule = [i for i in month_starts(days) if i - 1 >= lookback]
    if not schedule or not closes:
        return None
    start = schedule[0]
    rebalance = set(schedule)
    n = len(closes)
    w = [1.0 / n] * n
    value = 1.0 - cost_rate
    for t in range(start + 1, len(days)):
        grown = [w[i] * closes[i][t] / closes[i][t - 1] for i in range(n)]
        gross = sum(grown)
        value *= gross
        w = [g / gross for g in grown]
        if t in rebalance:
            value *= 1 - sum(abs(x - 1.0 / n) for x in w) * cost_rate
            w = [1.0 / n] * n
    years = (len(days) - 1 - start) / TRADING_DAYS
    return value ** (1 / years) - 1 if years > 0 and value > 0 else None


def monthly_returns(daily: Sequence[float], step: int = 21) -> list[float]:
    """Compound daily returns into consecutive ``step``-session returns."""
    out = []
    for a in range(0, len(daily) - step + 1, step):
        g = 1.0
        for r in daily[a : a + step]:
            g *= 1 + r
        out.append(g - 1)
    return out


def goal_paths(
    monthly: Sequence[float],
    years: int,
    initial: float,
    contribution: float,
    samples: int = 2000,
    block: int = 3,
    seed: int = 23,
) -> list[list[float]]:
    """Wealth at each year end for ``samples`` paths built from blocks of consecutive historical
    months (block bootstrap, fixed seed). Contributions are added at each month start."""
    n = len(monthly)
    if n < block * 4:
        return []
    rng = random.Random(seed)
    months = years * 12
    paths = []
    for _ in range(samples):
        w = initial
        row = []
        m = 0
        while m < months:
            s = rng.randrange(n - block + 1)
            for r in monthly[s : s + block]:
                if m >= months:
                    break
                w = (w + contribution) * (1 + r)
                m += 1
                if m % 12 == 0:
                    row.append(w)
        paths.append(row)
    return paths


def quantile(values: Sequence[float], q: float) -> float:
    v = sorted(values)
    return v[min(len(v) - 1, max(0, int(q * (len(v) - 1))))]
