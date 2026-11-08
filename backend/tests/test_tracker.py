import asyncio
import math
from datetime import UTC, date, datetime, timedelta

import pytest

from app.agents.base import PriceSeries
from app.db import Database
from app.errors import AppError
from app.schemas.market import NewsItem
from app.schemas.tracker import PositionIn
from app.services.instruments import InstrumentService
from app.services.planner import AssetData
from app.services.tracker import TrackerService
from app.tools import tracking as T
from app.tools.market_hours import IST

# --- pure helpers ---------------------------------------------------------------------------


def test_start_cutoff_uses_the_close_known_at_that_moment():
    before_close = datetime(2026, 11, 3, 14, 0, tzinfo=IST)
    after_close = datetime(2026, 11, 3, 16, 0, tzinfo=IST)
    assert T.start_cutoff(before_close) == date(2026, 11, 2)
    assert T.start_cutoff(after_close) == date(2026, 11, 3)


def test_period_return_and_close_lookup():
    pts = [(date(2026, 11, 2), 100.0), (date(2026, 11, 4), 110.0)]
    assert T.close_on_or_before(pts, date(2026, 11, 3)) == (date(2026, 11, 2), 100.0)
    assert T.close_on_or_before(pts, date(2026, 11, 1)) is None
    assert math.isclose(T.period_return(pts, date(2026, 11, 3), 121.0), 0.21)


def test_big_moves_need_two_percent_and_twice_the_usual_move():
    pts = [(date(2026, 9, 1) + timedelta(days=i), 100.0 + (0.3 if i % 2 else 0)) for i in range(40)]
    pts.append((date(2026, 10, 15), pts[-1][1] * 1.05))
    pts.append((date(2026, 10, 16), pts[-1][1] * 1.01))
    moves = T.big_moves(
        pts, date(2026, 10, 10), live_price=pts[-1][1] * 0.97, today=date(2026, 10, 17)
    )
    assert [(d, round(r, 2), live) for d, r, live in moves] == [
        (date(2026, 10, 15), 0.05, False),
        (date(2026, 10, 17), -0.03, True),
    ]


def test_driver_names_the_dominant_part():
    assert T.driver_of(0.05, 0.045, 0.04) == "market"
    assert T.driver_of(-0.08, 0.0, 0.01) == "stock"
    assert T.driver_of(0.06, 0.06, 0.0) == "sector"
    assert T.driver_of(0.02, None, None) == "mixed"


# --- service, offline ---------------------------------------------------------------------

DAY0 = date(2026, 9, 1)


def _closes(start: float, step: float, n: int) -> list[float]:
    return [start * (1 + step) ** i for i in range(n)]


class FakePortfolio:
    def __init__(self, closes: dict[str, list[float]]):
        self.closes = closes

    async def _asset(self, inst, role="holding", divs=True):
        c = self.closes[inst.symbol]
        times = [((DAY0 - date(1970, 1, 1)).days + i - 1) * 86400 for i in range(len(c))]
        series = PriceSeries(inst.symbol, times, c, "test", datetime.now(UTC))
        return AssetData(inst, "IT", series, [])


class FakeData:
    async def quotes_for(self, insts):
        return {}

    async def headlines(self, inst):
        when = datetime.now(UTC) - timedelta(days=1)
        return [
            NewsItem(
                title=f"{inst.symbol} shares surge on strong results",
                link="https://x/1",
                publisher="P",
                published_at=when,
            )
        ], []

    async def dividends(self, symbol):
        return []


class FakeResearch:
    def latest(self, key):
        return None

    def report_at(self, key, when):
        return None

    def enqueue(self, key, force=False):
        self.last = key


def _seed(db):
    now = datetime.now(UTC)
    for key, seg, sym in [
        ("NSE_EQ|INAAA", "NSE_EQ", "AAA"),
        ("NSE_EQ|INBBB", "NSE_EQ", "BBB"),
        ("NSE_INDEX|Nifty 50", "NSE_INDEX", "NIFTY"),
    ]:
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
                f"IN{sym}",
                "1",
                1,
                0.05,
                "test",
                now,
            ],
        )


def _service(n_days: int):
    db = Database(":memory:")
    _seed(db)
    closes = {
        "AAA": _closes(100, 0.002, n_days),
        "BBB": _closes(200, -0.001, n_days),
        "NIFTY": _closes(20000, 0.001, n_days),
    }
    svc = TrackerService(
        db, InstrumentService(db, None), FakeData(), FakePortfolio(closes), FakeResearch()
    )
    return svc, closes


def test_positions_are_priced_from_real_closes_and_amounts_buy_whole_shares():
    n = (date.today() - DAY0).days + 1
    svc, closes = _service(n)

    async def run():
        pid = svc.create("Long term")
        await svc.add_position(
            pid, PositionIn(symbol="AAA", quantity=10, entry_date=DAY0 + timedelta(days=5))
        )
        await svc.add_position(pid, PositionIn(symbol="bbb", amount=1000))
        with pytest.raises(AppError):
            await svc.add_position(pid, PositionIn(symbol="AAA", amount=10))  # buys no whole share
        p = await svc.portfolio(pid)
        aaa = next(x for x in p.positions if x.symbol == "AAA")
        bbb = next(x for x in p.positions if x.symbol == "BBB")
        assert math.isclose(aaa.entry_price, closes["AAA"][5])
        assert (
            bbb.quantity == math.floor(1000 / closes["BBB"][-1]) and "last close" in bbb.entry_basis
        )
        assert math.isclose(p.cost, aaa.cost + bbb.cost)
        return pid

    asyncio.run(run())


def test_review_contributions_add_up_and_explain_each_stock():
    n = (date.today() - DAY0).days + 1
    svc, closes = _service(n)

    async def run():
        pid = svc.create("Test")
        await svc.add_position(
            pid, PositionIn(symbol="AAA", quantity=10, entry_date=DAY0 + timedelta(days=5))
        )
        await svc.add_position(
            pid, PositionIn(symbol="BBB", quantity=5, entry_date=DAY0 + timedelta(days=5))
        )
        r = await svc.review(pid, "1w")
        assert math.isclose(sum(s.contribution for s in r.stocks), r.change, abs_tol=1e-6)
        assert math.isclose(r.end_value - r.start_value, r.change, abs_tol=1e-6)
        assert r.benchmark_return is not None and r.market_part is not None
        # The market part is what the same money would have made in the index, stock by stock.
        like_for_like = sum(s.quantity * s.start_price * s.market_return for s in r.stocks)
        assert math.isclose(r.market_part, like_for_like)
        assert math.isclose(r.selection_part, r.change - r.market_part)
        assert {s.symbol for s in r.stocks} == {"AAA", "BBB"}
        aaa = next(s for s in r.stocks if s.symbol == "AAA")
        assert aaa.contribution > 0 and "AAA" in aaa.explanation and "NIFTY 50" in aaa.explanation
        assert aaa.headlines and aaa.headlines[0].tone == "positive"
        assert r.value_series and len(r.value_series) == len(r.cost_series)
        assert r.facts and "Past week" in r.headline
        # The first visit falls back to "since you started"; once marked seen it uses the visit.
        first = await svc.review(pid, "last_visit")
        assert first.period_label.startswith("Since you started")
        svc.mark_viewed(pid)
        later = await svc.review(pid, "last_visit")
        assert later.period_label == "Since your last visit"

    asyncio.run(run())
