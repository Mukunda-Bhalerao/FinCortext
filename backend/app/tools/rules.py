"""Rule-based strategies on daily bars: indicators, signals and a backtest. Pure Python, no I/O.

Timing, to keep the future out of every decision:
- conditions are evaluated on a session's close, using only that close and earlier ones;
- the order they trigger fills at the next session's open;
- a stop-loss or target is checked against each later session's low and high; a gap through
  the level fills at the open instead (worse for a stop, better for a target). If one session
  touches both, the stop is assumed to come first.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from app.schemas.strategy import Condition, Rules
from app.tools.charges import order_charges

YEAR_HIGH = 252


@dataclass(frozen=True)
class Bar:
    day: date
    open: float
    high: float
    low: float
    close: float


# --- indicators as series ---------------------------------------------------------------------


def sma_series(closes: Sequence[float], n: int) -> list[float | None]:
    out: list[float | None] = [None] * len(closes)
    total = 0.0
    for i, c in enumerate(closes):
        total += c
        if i >= n:
            total -= closes[i - n]
        if i >= n - 1:
            out[i] = total / n
    return out


def rsi_series(closes: Sequence[float], n: int = 14) -> list[float | None]:
    """Wilder's RSI."""
    out: list[float | None] = [None] * len(closes)
    if len(closes) <= n:
        return out
    gains = losses = 0.0
    for i in range(1, n + 1):
        d = closes[i] - closes[i - 1]
        gains += max(d, 0.0)
        losses += max(-d, 0.0)
    avg_g, avg_l = gains / n, losses / n

    def value(g: float, lo: float) -> float:
        return 100.0 if lo == 0 else 100 - 100 / (1 + g / lo)

    out[n] = value(avg_g, avg_l)
    for i in range(n + 1, len(closes)):
        d = closes[i] - closes[i - 1]
        avg_g = (avg_g * (n - 1) + max(d, 0.0)) / n
        avg_l = (avg_l * (n - 1) + max(-d, 0.0)) / n
        out[i] = value(avg_g, avg_l)
    return out


def return_series(closes: Sequence[float], n: int) -> list[float | None]:
    return [
        closes[i] / closes[i - n] - 1 if i >= n and closes[i - n] > 0 else None
        for i in range(len(closes))
    ]


def from_high_series(bars: Sequence[Bar], n: int = YEAR_HIGH) -> list[float | None]:
    """Close against the highest high of the last ``n`` sessions (0 at the high, negative
    below it). Needs a full window."""
    out: list[float | None] = [None] * len(bars)
    for i in range(n - 1, len(bars)):
        high = max(b.high for b in bars[i - n + 1 : i + 1])
        out[i] = bars[i].close / high - 1 if high > 0 else None
    return out


# --- conditions ---------------------------------------------------------------------------------


def _pct(v: float) -> str:
    return f"{v * 100:g}%"


def describe(c: Condition) -> str:
    verb = {
        "above": "is above",
        "below": "is below",
        "crosses_above": "crosses above",
        "crosses_below": "crosses below",
    }[c.op]
    if c.kind == "price_vs_sma":
        return f"price {verb} its {c.n}-day average"
    if c.kind == "sma_cross":
        return f"{c.n}-day average {verb} the {c.m}-day average"
    if c.kind == "rsi":
        return f"RSI({c.n}) {verb} {c.value:g}"
    if c.kind == "return":
        return f"{c.n}-day return {verb} {_pct(c.value or 0)}"
    if c.op == "below":
        return f"price is at least {_pct(c.value or 0)} below its 52-week high"
    return f"price is within {_pct(c.value or 0)} of its 52-week high"


def describe_rules(r: Rules) -> list[str]:
    out = ["Buy when " + " and ".join(describe(c) for c in r.entry) + "."]
    exits = [describe(c) for c in r.exit]
    if r.stop_loss:
        exits.append(f"the price falls {_pct(r.stop_loss)} below the buy price (stop-loss)")
    if r.take_profit:
        exits.append(f"the price rises {_pct(r.take_profit)} above the buy price (target)")
    if r.max_days:
        exits.append(f"{r.max_days} days have passed")
    out.append("Sell when " + " or ".join(exits) + ".")
    return out


class Signals:
    """Evaluates conditions on a bar series; indicator series are computed once."""

    def __init__(self, bars: Sequence[Bar]):
        self.bars = bars
        self.closes = [b.close for b in bars]
        self._cache: dict[tuple, list[float | None]] = {}

    def _series(self, key: tuple) -> list[float | None]:
        if key not in self._cache:
            kind, n = key
            if kind == "sma":
                self._cache[key] = sma_series(self.closes, n)
            elif kind == "rsi":
                self._cache[key] = rsi_series(self.closes, n)
            elif kind == "ret":
                self._cache[key] = return_series(self.closes, n)
            else:
                self._cache[key] = from_high_series(self.bars)
        return self._cache[key]

    def _pair(self, c: Condition, i: int) -> tuple[float | None, float | None]:
        """(left, right) of the comparison at bar ``i``."""
        if c.kind == "price_vs_sma":
            return self.closes[i], self._series(("sma", c.n))[i]
        if c.kind == "sma_cross":
            return self._series(("sma", c.n))[i], self._series(("sma", c.m or c.n))[i]
        if c.kind == "rsi":
            return self._series(("rsi", c.n))[i], c.value
        if c.kind == "return":
            return self._series(("ret", c.n))[i], c.value
        v = self._series(("high", YEAR_HIGH))[i]
        return v, -(c.value or 0)

    def holds(self, c: Condition, i: int) -> bool:
        a, b = self._pair(c, i)
        if a is None or b is None:
            return False
        if c.op == "above":
            return a > b
        if c.op == "below":
            return a <= b if c.kind == "from_high" else a < b
        if i == 0:
            return False
        pa, pb = self._pair(c, i - 1)
        if pa is None or pb is None:
            return False
        if c.op == "crosses_above":
            return pa <= pb and a > b
        return pa >= pb and a < b

    def all(self, cs: Sequence[Condition], i: int) -> bool:
        return all(self.holds(c, i) for c in cs)

    def any(self, cs: Sequence[Condition], i: int) -> bool:
        return any(self.holds(c, i) for c in cs)


# --- backtest -----------------------------------------------------------------------------------


@dataclass
class Trade:
    entry_i: int
    entry_price: float
    quantity: int
    buy_charges: float
    exit_i: int | None = None
    exit_price: float | None = None
    exit_reason: str | None = None
    sell_charges: float = 0.0

    @property
    def net(self) -> float:
        assert self.exit_price is not None
        return (
            (self.exit_price - self.entry_price) * self.quantity
            - self.buy_charges
            - self.sell_charges
        )


@dataclass
class Run:
    start_i: int
    trades: list[Trade]
    equity: list[float]  # one value per bar from start_i, at the close
    charges: float
    held_days: int


def run_rules(
    bars: Sequence[Bar], rules: Rules, start_i: int, capital: float, plan: str = "zero"
) -> Run:
    """Simulate the rules from bar ``start_i`` (earlier bars only warm the indicators up)."""
    sig = Signals(bars)
    cash = capital
    pos: Trade | None = None
    pending: str | None = None  # "buy" or an exit reason, to execute at the next open
    trades: list[Trade] = []
    equity: list[float] = []
    charges = 0.0
    held = 0

    def sell(i: int, price: float, reason: str) -> None:
        nonlocal cash, pos, charges
        assert pos is not None
        value = price * pos.quantity
        ch = order_charges("SELL", value, plan).total
        cash += value - ch
        charges += ch
        pos.exit_i, pos.exit_price, pos.exit_reason, pos.sell_charges = i, price, reason, ch
        trades.append(pos)
        pos = None

    for i in range(start_i, len(bars)):
        bar = bars[i]
        # 1) orders decided at the previous close fill at this open
        if pending == "buy" and pos is None:
            qty = math.floor(cash / (bar.open * 1.002))
            if qty >= 1:
                value = qty * bar.open
                ch = order_charges("BUY", value, plan).total
                cash -= value + ch
                charges += ch
                pos = Trade(i, bar.open, qty, ch)
        elif pending and pending != "buy" and pos is not None:
            sell(i, bar.open, pending)
        pending = None
        # 2) stop and target during the session
        if pos is not None:
            stop = pos.entry_price * (1 - rules.stop_loss) if rules.stop_loss else None
            target = pos.entry_price * (1 + rules.take_profit) if rules.take_profit else None
            if stop is not None and bar.low <= stop:
                sell(i, min(bar.open, stop) if i > pos.entry_i else stop, "stop-loss")
            elif target is not None and bar.high >= target:
                sell(i, max(bar.open, target) if i > pos.entry_i else target, "target")
        # 3) decisions at the close
        if pos is not None:
            held += 1
            days = i - pos.entry_i
            if rules.exit and sig.any(rules.exit, i):
                pending = "exit signal"
            elif rules.max_days and days >= rules.max_days:
                pending = f"held {rules.max_days} days"
        elif sig.all(rules.entry, i) and i + 1 < len(bars):
            pending = "buy"
        equity.append(cash + (pos.quantity * bar.close if pos else 0.0))
    if pos is not None:  # still open: valued at the last close, not sold
        pos.exit_i, pos.exit_price, pos.exit_reason = len(bars) - 1, bars[-1].close, "still held"
        trades.append(pos)
    return Run(start_i, trades, equity, charges, held)


def max_drawdown(values: Sequence[float]) -> float:
    peak, worst = -math.inf, 0.0
    for v in values:
        peak = max(peak, v)
        if peak > 0:
            worst = min(worst, v / peak - 1)
    return worst


def hold_curve(bars: Sequence[Bar], start_i: int, capital: float, plan: str) -> list[float]:
    """Buy at the first open of the period, hold, value at each close (after buy charges)."""
    first = bars[start_i].open
    qty = math.floor(capital / (first * 1.002))
    if qty < 1:
        return [capital] * (len(bars) - start_i)
    ch = order_charges("BUY", qty * first, plan).total
    cash = capital - qty * first - ch
    return [cash + qty * b.close for b in bars[start_i:]]
