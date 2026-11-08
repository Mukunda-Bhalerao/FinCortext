import math
from datetime import date, timedelta

import pytest
from pydantic import ValidationError

from app.schemas.strategy import Condition, Rules
from app.tools import rules as R
from app.tools.charges import order_charges


def _bars(closes, opens=None, lows=None, highs=None):
    d0 = date(2024, 1, 1)
    return [
        R.Bar(
            d0 + timedelta(days=i),
            (opens or closes)[i],
            (highs or closes)[i],
            (lows or closes)[i],
            c,
        )
        for i, c in enumerate(closes)
    ]


def test_indicators():
    assert R.sma_series([1, 2, 3, 4], 2) == [None, 1.5, 2.5, 3.5]
    up = R.rsi_series([float(i) for i in range(30)], 14)
    assert up[13] is None and up[14] == 100.0
    assert R.return_series([100, 110, 121], 2)[2] == pytest.approx(0.21)
    bars = _bars([10, 12, 9], highs=[10, 12, 9])
    assert R.from_high_series(bars, 3)[2] == pytest.approx(9 / 12 - 1)


def test_crossovers_need_a_change_of_side():
    bars = _bars([10, 10, 10, 9, 12, 13])
    sig = R.Signals(bars)
    cross = Condition(kind="price_vs_sma", op="crosses_above", n=3)
    assert [sig.holds(cross, i) for i in range(6)] == [False, False, False, False, True, False]


def test_trades_fill_at_the_next_open_never_the_signal_close():
    closes = [100, 100, 100, 100, 120, 130, 140]
    opens = [100, 100, 100, 100, 118, 125, 139]
    bars = _bars(closes, opens=opens)
    rules = Rules(
        entry=[Condition(kind="price_vs_sma", op="crosses_above", n=3)],
        max_days=1,
    )
    run = R.run_rules(bars, rules, 3, 100_000)
    t = run.trades[0]
    # Signal on bar 4's close (120); the buy fills at bar 5's open (125), not at 120.
    assert t.entry_i == 5 and t.entry_price == 125
    # Held one session, the exit is decided on bar 6's close and fills at the next open:
    # there is none, so the position is reported as still held at the last close.
    assert t.exit_reason == "still held"


def test_a_stop_gapped_through_fills_at_the_open():
    closes = [100, 100, 100, 105, 100, 80]
    opens = [100, 100, 100, 100, 104, 85]
    lows = [100, 100, 100, 100, 99, 80]
    bars = _bars(closes, opens=opens, lows=lows)
    rules = Rules(entry=[Condition(kind="return", op="above", n=1, value=0.01)], stop_loss=0.1)
    run = R.run_rules(bars, rules, 2, 100_000)
    t = run.trades[0]
    assert t.entry_price == 104  # bought at the open after the +5% day
    assert t.exit_reason == "stop-loss" and t.exit_price == 85  # gap below the 93.6 stop
    qty = t.quantity
    expected_cash = (
        100_000
        - qty * 104
        - order_charges("BUY", qty * 104).total
        + qty * 85
        - order_charges("SELL", qty * 85).total
    )
    assert math.isclose(run.equity[-1], expected_cash)


def test_rules_need_an_exit_and_read_plainly():
    with pytest.raises(ValidationError):
        Rules(entry=[Condition(kind="rsi", op="below", n=14, value=30)])
    r = Rules(
        entry=[
            Condition(kind="rsi", op="below", n=14, value=30),
            Condition(kind="price_vs_sma", op="above", n=200),
        ],
        stop_loss=0.08,
        take_profit=0.15,
    )
    assert R.describe_rules(r) == [
        "Buy when RSI(14) is below 30 and price is above its 200-day average.",
        "Sell when the price falls 8% below the buy price (stop-loss) or the price rises "
        "15% above the buy price (target).",
    ]
