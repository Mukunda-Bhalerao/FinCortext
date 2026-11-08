"""Pure helpers for reviewing a tracked portfolio over a period. No I/O.

Daily closes are (IST session date, close) pairs, oldest first. A period that starts at a
moment in time is measured from the last close that was already known at that moment: the
same day's close when the moment is after 15:30 IST, otherwise the previous session's close.
"""

import bisect
import math
from collections.abc import Sequence
from datetime import date, datetime, time, timedelta

from app.tools.market_hours import to_ist

SESSION_CLOSE = time(15, 30)
Points = Sequence[tuple[date, float]]


def start_cutoff(moment: datetime) -> date:
    """Latest session date whose close was known at ``moment``."""
    ist = to_ist(moment)
    return ist.date() if ist.time() >= SESSION_CLOSE else ist.date() - timedelta(days=1)


def close_on_or_before(points: Points, day: date) -> tuple[date, float] | None:
    i = bisect.bisect_right([d for d, _ in points], day)
    return points[i - 1] if i else None


def period_return(points: Points, cutoff: date, end_price: float | None = None) -> float | None:
    """Return from the close on or before ``cutoff`` to ``end_price`` (or the last close)."""
    start = close_on_or_before(points, cutoff)
    end = end_price if end_price is not None else (points[-1][1] if points else None)
    if start is None or not end or start[1] <= 0:
        return None
    return end / start[1] - 1


def big_moves(
    points: Points,
    after: date,
    live_price: float | None = None,
    today: date | None = None,
    limit: int = 3,
) -> list[tuple[date, float, bool]]:
    """The largest daily moves after ``after``: at least 2% and at least twice the stock's
    typical daily move over the 60 sessions before. Today's move so far is included when
    ``live_price`` is newer than the last close. Returns (date, change, is_live)."""
    if len(points) < 2:
        return []
    rets = [(points[i][0], points[i][1] / points[i - 1][1] - 1) for i in range(1, len(points))]
    before = [r for d, r in rets if d <= after][-60:]
    sd = math.sqrt(sum(r * r for r in before) / len(before)) if len(before) >= 10 else 0.0
    floor = max(0.02, 2 * sd)
    window = [(d, r, False) for d, r in rets if d > after]
    if live_price and today and points[-1][1] > 0:
        if points[-1][0] < today:
            window.append((today, live_price / points[-1][1] - 1, True))
    picked = [m for m in window if abs(m[1]) >= floor]
    picked.sort(key=lambda m: -abs(m[1]))
    return sorted(picked[:limit], key=lambda m: m[0])


def driver_of(stock: float, sector: float | None, market: float | None) -> str:
    """Which part explains most of a stock's move: the market, its sector's move beyond the
    market, or the stock's own move beyond its sector."""
    if market is None:
        return "mixed"
    parts = {"market": market}
    if sector is not None:
        parts["sector"] = sector - market
        parts["stock"] = stock - sector
    else:
        parts["stock"] = stock - market
    total = sum(abs(v) for v in parts.values())
    if total == 0:
        return "mixed"
    name, value = max(parts.items(), key=lambda kv: abs(kv[1]))
    return name if abs(value) / total >= 0.5 else "mixed"


def holdings_value(
    series: dict[str, Points], quantities: dict[str, float], entries: dict[str, date], day: date
) -> float:
    """Value on ``day`` of the positions entered on or before it, at that day's close."""
    total = 0.0
    for key, pts in series.items():
        if entries[key] > day:
            continue
        c = close_on_or_before(pts, day)
        if c is not None:
            total += quantities[key] * c[1]
    return total
