"""Charges on one NSE equity delivery order, itemised the way a broker's contract note shows
them. Rates come from ``backtest.CostModel`` so paper trades, backtests and the planner use one
schedule. STT and stamp duty are rounded to the rupee as the exchanges levy them.
"""

from dataclasses import asdict, dataclass
from typing import Literal

from app.tools.backtest import CostModel

Side = Literal["BUY", "SELL"]
Plan = Literal["zero", "flat20"]

PLANS: dict[str, str] = {
    "zero": "Zero brokerage on delivery (most discount brokers)",
    "flat20": "Rs 20 or 0.1% per order, whichever is lower (min Rs 5)",
}
RATES = CostModel()


@dataclass(frozen=True)
class Charges:
    brokerage: float
    stt: float
    exchange: float
    sebi: float
    stamp: float
    gst: float
    dp: float
    total: float

    def as_dict(self) -> dict[str, float]:
        return asdict(self)


def brokerage(value: float, plan: str) -> float:
    if plan == "flat20":
        return round(max(5.0, min(20.0, value * 0.001)), 2) if value > 0 else 0.0
    return 0.0


def order_charges(
    side: Side, value: float, plan: str = "zero", rates: CostModel = RATES
) -> Charges:
    """Charges for one delivery order worth ``value`` rupees. The DP charge applies once per
    stock sold per day; it is charged on each sell order here, which matches one sell a day."""
    if value <= 0:
        return Charges(0, 0, 0, 0, 0, 0, 0, 0)
    b = brokerage(value, plan)
    stt = float(round(value * rates.stt))
    exchange = round(value * rates.exchange, 2)
    sebi = round(value * rates.sebi, 2)
    stamp = float(round(value * rates.stamp_buy)) if side == "BUY" else 0.0
    gst = round((b + exchange + sebi) * rates.gst, 2)
    dp = rates.dp_per_sell if side == "SELL" else 0.0
    total = round(b + stt + exchange + sebi + stamp + gst + dp, 2)
    return Charges(b, stt, exchange, sebi, stamp, gst, dp, total)


def break_even(buy_price: float, quantity: float, plan: str = "zero") -> float:
    """Sell price at which a round trip (buy then sell) makes exactly zero after charges."""
    buy_value = buy_price * quantity
    cost = buy_value + order_charges("BUY", buy_value, plan).total
    price = cost / quantity
    for _ in range(20):  # sell charges depend on the sell value: iterate to a fixed point
        sell = order_charges("SELL", price * quantity, plan).total
        nxt = (cost + sell) / quantity
        if abs(nxt - price) < 1e-6:
            break
        price = nxt
    return price
