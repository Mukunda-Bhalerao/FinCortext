import asyncio
import math
from datetime import UTC, date, datetime, timedelta

import pytest

from app.db import Database
from app.errors import AppError
from app.schemas.market import Quote
from app.schemas.paper import OrderIn
from app.services.instruments import InstrumentService
from app.services.paper import PaperService, next_session
from app.services.tracker import TrackerService
from app.tools.charges import break_even, order_charges
from app.tools.market_hours import IST

# --- charges -----------------------------------------------------------------------------


def test_delivery_charges_match_the_published_schedule():
    buy = order_charges("BUY", 100_000)
    # STT 0.1%, stamp 0.015%, NSE 0.00297%, SEBI Rs 10 a crore, GST 18% on fees
    assert (buy.stt, buy.stamp, buy.exchange, buy.sebi) == (100, 15, 2.97, 0.1)
    assert buy.gst == round((2.97 + 0.1) * 0.18, 2)
    assert math.isclose(buy.total, 100 + 15 + 2.97 + 0.1 + buy.gst)
    sell = order_charges("SELL", 100_000)
    assert sell.stamp == 0 and sell.dp == 15.93
    flat = order_charges("BUY", 100_000, "flat20")
    assert flat.brokerage == 20 and order_charges("BUY", 1_000, "flat20").brokerage == 5


def test_break_even_covers_both_sides():
    be = break_even(100, 100)
    sell_value = be * 100
    net = sell_value - order_charges("SELL", sell_value).total
    assert math.isclose(net, 100 * 100 + order_charges("BUY", 10_000).total, abs_tol=0.01)


def test_orders_after_the_close_belong_to_the_next_weekday():
    friday_evening = datetime(2026, 11, 6, 16, 0, tzinfo=IST)
    assert next_session(friday_evening).isoformat() == "2026-11-09"
    assert next_session(datetime(2026, 11, 9, 9, 0, tzinfo=IST)).isoformat() == "2026-11-09"


# --- engine --------------------------------------------------------------------------------


class Clock:
    def __init__(self):
        self.open = True

    def state(self):
        return ("open" if self.open else "closed", True)


class Data:
    def __init__(self):
        self.prices = {"NSE_EQ|INAAA": 100.0, "NSE_INDEX|Nifty 50": 20000.0}

    async def quotes_for(self, insts):
        now = datetime.now(UTC)
        return {
            i.instrument_key: Quote(
                instrument_key=i.instrument_key,
                ltp=self.prices[i.instrument_key],
                prev_close=self.prices[i.instrument_key],
                change=0.0,
                change_pct=0.0,
                last_trade_time=now,
                source="test",
                fetched_at=now,
                freshness="live",
            )
            for i in insts
            if i.instrument_key in self.prices
        }


class Research:
    def enqueue(self, key, force=False):
        pass


def _seed(db):
    now = datetime.now(UTC)
    for key, seg, sym in [
        ("NSE_EQ|INAAA", "NSE_EQ", "AAA"),
        ("NSE_INDEX|Nifty 50", "NSE_INDEX", "NIFTY"),
    ]:
        db.execute(
            "INSERT INTO instruments VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [key, seg, "NSE", "EQ", sym, sym, sym, f"IN{sym}", "1", 1, 0.05, "test", now],
        )


def _setup():
    db = Database(":memory:")
    _seed(db)
    data, clock = Data(), Clock()
    instruments = InstrumentService(db, None)
    tracker = TrackerService(db, instruments, data, None, Research())
    paper = PaperService(db, instruments, data, tracker, clock)
    pid = tracker.create("Practice", "paper", 100_000)
    return db, data, clock, tracker, paper, pid


def test_market_buy_fills_and_its_target_closes_the_trade():
    db, data, clock, tracker, paper, pid = _setup()

    async def run():
        o = await paper.place(
            pid,
            OrderIn(
                symbol="AAA",
                side="BUY",
                quantity=100,
                reason="Results beat estimates",
                tag="Results",
                target_price=110,
                stop_price=95,
            ),
        )
        assert o.status == "FILLED" and o.fill_price == 100
        buy_cost = 10_000 + order_charges("BUY", 10_000).total
        p = await tracker.portfolio(pid)
        assert math.isclose(p.cash, 100_000 - buy_cost)
        assert p.positions[0].reason == "Results beat estimates"
        exits = [x for x in paper.orders(pid) if x.status == "OPEN"]
        assert {(x.kind, x.limit_price or x.trigger_price) for x in exits} == {
            ("LIMIT", 110),
            ("SL", 95),
        }
        data.prices["NSE_EQ|INAAA"] = 111.0
        data.prices["NSE_INDEX|Nifty 50"] = 20200.0
        assert await paper.match() == 1
        statuses = sorted(x.status for x in paper.orders(pid))
        assert statuses == ["CANCELLED", "FILLED", "FILLED"]  # the stop is cancelled
        [trade] = paper.trades(pid)
        sell_charges = order_charges("SELL", 11_100).total
        assert math.isclose(trade.net, 1_100 - order_charges("BUY", 10_000).total - sell_charges)
        assert math.isclose(trade.index_return, 0.01) and trade.beat_index
        p = await tracker.portfolio(pid)
        assert p.positions == [] and math.isclose(p.realized, trade.net)
        assert math.isclose(p.cash, 100_000 + trade.net)
        act = await paper.activity(pid)
        assert act.scorecard.closed_trades == 1 and act.scorecard.wins == 1
        assert "ahead of the market" in act.journal[0].verdict

    asyncio.run(run())


def test_closed_market_orders_wait_and_reserve_cash():
    db, data, clock, tracker, paper, pid = _setup()
    clock.open = False

    async def run():
        o = await paper.place(pid, OrderIn(symbol="AAA", side="BUY", quantity=900))
        assert o.status == "OPEN"
        assert tracker.reserved_cash(pid) > 90_000
        with pytest.raises(AppError):  # the cash is already set aside for the first order
            await paper.place(pid, OrderIn(symbol="AAA", side="BUY", quantity=200))
        paper.cancel(pid, o.id)
        assert tracker.reserved_cash(pid) == 0

    asyncio.run(run())


def test_limit_orders_wait_for_their_price_and_sells_need_shares():
    db, data, clock, tracker, paper, pid = _setup()

    async def run():
        with pytest.raises(AppError):
            await paper.place(pid, OrderIn(symbol="AAA", side="SELL", quantity=1))
        o = await paper.place(
            pid, OrderIn(symbol="AAA", side="BUY", kind="LIMIT", limit_price=98, quantity=10)
        )
        assert o.status == "OPEN"
        data.prices["NSE_EQ|INAAA"] = 97.5
        await paper.match()
        o = paper.order(pid, o.id)
        assert o.status == "FILLED" and o.fill_price == 97.5  # filled at the better price

    asyncio.run(run())


def test_sells_close_the_oldest_lot_first():
    db, data, clock, tracker, paper, pid = _setup()

    async def run():
        await paper.place(pid, OrderIn(symbol="AAA", side="BUY", quantity=10, reason="first"))
        data.prices["NSE_EQ|INAAA"] = 120.0
        await paper.place(pid, OrderIn(symbol="AAA", side="BUY", quantity=10, reason="second"))
        await paper.place(pid, OrderIn(symbol="AAA", side="SELL", quantity=15))
        trades = sorted(paper.trades(pid), key=lambda t: t.buy_price)
        assert [(t.buy_price, t.quantity, t.buy_reason) for t in trades] == [
            (100, 10, "first"),
            (120, 5, "second"),
        ]
        p = await tracker.portfolio(pid)
        assert [(x.quantity, x.entry_price) for x in p.positions] == [(5, 120)]

    asyncio.run(run())


def test_tracking_portfolios_cannot_take_orders():
    db, data, clock, tracker, paper, _ = _setup()
    tid = tracker.create("Mine")

    async def run():
        with pytest.raises(AppError):
            await paper.place(tid, OrderIn(symbol="AAA", side="BUY", quantity=1))

    asyncio.run(run())


def test_day_orders_expire_after_their_session():
    db, data, clock, tracker, paper, pid = _setup()
    clock.open = False

    async def run():
        o = await paper.place(
            pid, OrderIn(symbol="AAA", side="BUY", kind="LIMIT", limit_price=50, quantity=1)
        )
        yesterday = (datetime.now(IST) - timedelta(days=1)).date()
        db.execute("UPDATE paper_orders SET session = ? WHERE id = ?", [yesterday, o.id])
        await paper.match()
        assert paper.order(pid, o.id).status == "EXPIRED"

    asyncio.run(run())


# --- strategies running forward -------------------------------------------------------------


class Candles:
    """Daily candles for AAA ending today: flat, then a 3% jump on the last session."""

    def __init__(self, today):
        self.today = today

    async def series(self, key, tf):
        from app.schemas.market import Candle, CandleSeries

        closes = [100.0] * 30 + [103.0]
        days = [self.today - timedelta(days=len(closes) - 1 - i) for i in range(len(closes))]
        candles = [
            Candle(
                time=((d - date(1970, 1, 1)).days - 1) * 86400,  # candle start: IST midnight
                open=c,
                high=c,
                low=c,
                close=c,
                volume=1,
            )
            for d, c in zip(days, closes, strict=True)
        ]
        return CandleSeries(
            instrument_key=key,
            timeframe="1D",
            unit="days",
            interval=1,
            candles=candles,
            includes_current_session=True,
            source="test",
            fetched_at=datetime.now(UTC),
        )


def test_a_running_strategy_places_its_buy_after_the_close():
    from app.schemas.strategy import Condition, ForwardIn, Rules, StrategyIn
    from app.services.strategy import StrategyService

    db, data, clock, tracker, paper, pid = _setup()
    clock.open = False  # after the close: the order waits for the next open
    today = datetime.now(IST).date()
    lab = StrategyService(db, InstrumentService(db, None), Candles(today), paper, tracker, clock)
    rules = Rules(
        entry=[Condition(kind="return", op="above", n=1, value=0.02)], stop_loss=0.05, max_days=5
    )
    s = lab.save(StrategyIn(name="Jump", rules=rules, symbols=["aaa"]))
    lab.start(s.id, ForwardIn(portfolio_id=pid, per_trade=10_000))

    async def run():
        note = await lab.run_once(s.id, today)
        assert "buy order placed" in note
        [order] = [o for o in paper.orders(pid) if o.status == "OPEN"]
        assert order.side == "BUY" and order.source == f"strategy:{s.id}"
        assert order.tag == "Strategy" and "1-day return is above 2%" in order.reason
        assert order.stop_price == round(103 * 0.95, 2)
        # Run again the same day: no second order while the first is pending.
        await lab.run_once(s.id, today)
        assert len([o for o in paper.orders(pid) if o.status == "OPEN"]) == 1

    asyncio.run(run())
