"""Tracked portfolios: portfolios you build here and come back to.

Positions are recorded at a real price: the live price when you add them, or the close of the
day you say you bought (or your own price). Opening a portfolio reviews a period (since your
last visit, today, a week, a month, since the start) and explains each stock's contribution:
how much the market, its sector and the stock itself account for, its largest daily moves and
the headlines published around them, dividends, results and research changes. Headlines are
shown as what was reported at the time, not as proven causes.
"""

import asyncio
import contextlib
import logging
import math
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime, timedelta

from app.db import Database, _as_utc
from app.errors import AppError, NotFound
from app.schemas.insights import Fact, Narrative
from app.schemas.market import Instrument
from app.schemas.portfolio import CurvePoint
from app.schemas.tracker import (
    Dividend,
    Headline,
    Move,
    Period,
    PortfolioSummaryRow,
    Position,
    PositionIn,
    ResearchShift,
    Review,
    StockReview,
    TrackedPortfolio,
)
from app.services.insights import FactBook, pct
from app.services.instruments import InstrumentService
from app.services.portfolio import PortfolioService
from app.services.research import ResearchService
from app.services.research_data import SECTOR_INDEX, ResearchData
from app.tools import tracking as T
from app.tools.backtest import session_date
from app.tools.charges import break_even
from app.tools.headlines import score_headline
from app.tools.market_hours import to_ist
from app.tools.research_diff import SIGNAL_LABEL, diff_reports

log = logging.getLogger(__name__)

MAX_PORTFOLIOS = 20
DEFAULT_CASH = 100_000.0
MAX_POSITIONS = 40
SOURCE = "FinCortext portfolio tracker"
PERIOD_LABEL = {
    "last_visit": "Since your last visit",
    "today": "Today",
    "1w": "Past week",
    "1m": "Past month",
    "start": "Since you started",
}
DRIVER_TEXT = {
    "market": "the overall market",
    "sector": "its sector",
    "stock": "the company itself",
}
SMALL = 0.005  # gaps under half a percentage point read as "in line"


def nifty_moved(pts, start_day: date, now_price: float | None) -> bool:
    """Whether the index has a close after ``start_day`` or a live price different from it."""
    if not pts:
        return True  # unknown: do not claim the market was shut
    if pts[-1][0] > start_day:
        return True
    return now_price is not None and abs(now_price - pts[-1][1]) > 1e-9


def _points(v: float) -> str:
    n = abs(v) * 100
    return f"{n:.1f} percentage point{'' if round(n, 1) == 1 else 's'}"


def _rupees(v: float) -> str:
    sign = "-" if v < 0 else "+"
    return f"{sign}Rs {abs(v):,.0f}"


def _fmt_day(d: date) -> str:
    return f"{d.day} {d:%b}"


class TrackerService:
    def __init__(
        self,
        db: Database,
        instruments: InstrumentService,
        data: ResearchData,
        portfolio: PortfolioService,
        research: ResearchService,
        narrate: Callable[[str, list[str], list[Fact]], Awaitable[Narrative | None]] | None = None,
    ):
        self._db = db
        self._instruments = instruments
        self._data = data
        self._portfolio = portfolio
        self._research = research
        self._narrate = narrate

    # --- storage -------------------------------------------------------------------

    def keys(self) -> list[str]:
        """Every instrument held in a tracked portfolio (kept researched and watched)."""
        return [
            r[0] for r in self._db.fetchall("SELECT DISTINCT instrument_key FROM tracked_positions")
        ]

    def _row(self, pid: str) -> tuple:
        row = self._db.fetchone(
            "SELECT id, name, created_at, last_viewed_at FROM tracked_portfolios WHERE id = ?",
            [pid],
        )
        if row is None:
            raise NotFound("Portfolio not found.")
        return row

    def account(self, pid: str) -> tuple[str, float | None, float | None, str]:
        """(kind, starting cash, cash, brokerage plan)."""
        row = self._db.fetchone(
            "SELECT coalesce(kind, 'tracking'), starting_cash, cash, coalesce(plan, 'zero') "
            "FROM tracked_portfolios WHERE id = ?",
            [pid],
        )
        if row is None:
            raise NotFound("Portfolio not found.")
        return row

    def _require_tracking(self, pid: str) -> None:
        if self.account(pid)[0] == "paper":
            raise AppError(
                "This is a paper trading account: buy and sell through orders instead.",
                status_code=422,
            )

    def _positions(self, pid: str) -> list[tuple]:
        return self._db.fetchall(
            "SELECT id, instrument_key, quantity, entry_price, entry_at, entry_basis "
            "FROM tracked_positions WHERE portfolio_id = ? ORDER BY entry_at",
            [pid],
        )

    def create(
        self,
        name: str,
        kind: str = "tracking",
        starting_cash: float | None = None,
        plan: str = "zero",
    ) -> str:
        count = self._db.fetchone("SELECT count(*) FROM tracked_portfolios")
        if count and count[0] >= MAX_PORTFOLIOS:
            raise AppError(f"At most {MAX_PORTFOLIOS} portfolios.", status_code=422)
        cash = (starting_cash or DEFAULT_CASH) if kind == "paper" else None
        pid = uuid.uuid4().hex[:12]
        self._db.execute(
            "INSERT INTO tracked_portfolios (id, name, created_at, last_viewed_at, kind, "
            "starting_cash, cash, plan) VALUES (?, ?, ?, NULL, ?, ?, ?, ?)",
            [pid, name.strip(), datetime.now(UTC), kind, cash, cash, plan],
        )
        return pid

    def rename(self, pid: str, name: str) -> None:
        self._row(pid)
        self._db.execute("UPDATE tracked_portfolios SET name = ? WHERE id = ?", [name.strip(), pid])

    def delete(self, pid: str) -> None:
        self._row(pid)
        for table in ("paper_orders", "paper_trades"):
            self._db.execute(f"DELETE FROM {table} WHERE portfolio_id = ?", [pid])
        self._db.execute(
            "UPDATE strategies SET active = FALSE, portfolio_id = NULL WHERE portfolio_id = ?",
            [pid],
        )
        self._db.execute("DELETE FROM tracked_positions WHERE portfolio_id = ?", [pid])
        self._db.execute("DELETE FROM tracked_portfolios WHERE id = ?", [pid])

    def mark_viewed(self, pid: str) -> None:
        self._row(pid)
        self._db.execute(
            "UPDATE tracked_portfolios SET last_viewed_at = ? WHERE id = ?",
            [datetime.now(UTC), pid],
        )

    def remove_position(self, pid: str, position_id: str) -> None:
        self._require_tracking(pid)
        self._db.execute(
            "DELETE FROM tracked_positions WHERE portfolio_id = ? AND id = ?", [pid, position_id]
        )

    def set_quantity(self, pid: str, position_id: str, quantity: float) -> None:
        self._require_tracking(pid)
        self._db.execute(
            "UPDATE tracked_positions SET quantity = ? WHERE portfolio_id = ? AND id = ?",
            [quantity, pid, position_id],
        )

    async def add_position(self, pid: str, req: PositionIn) -> None:
        self._row(pid)
        self._require_tracking(pid)
        if len(self._positions(pid)) >= MAX_POSITIONS:
            raise AppError(f"At most {MAX_POSITIONS} stocks per portfolio.", status_code=422)
        inst = self._instruments.by_symbol(req.symbol.upper().strip())
        if inst.segment != "NSE_EQ":
            raise AppError("Only NSE equities can be added.", status_code=422)
        now = datetime.now(UTC)
        today = to_ist(now).date()
        if req.entry_date and req.entry_date > today:
            raise AppError("The purchase date cannot be in the future.", status_code=422)
        if req.entry_date and req.entry_date < today:
            series = await self._points(inst)
            close = T.close_on_or_before(series, req.entry_date)
            if close is None:
                raise AppError(f"No price history for {inst.symbol} on that date.", status_code=422)
            entry_at = datetime(close[0].year, close[0].month, close[0].day, 10, 0, tzinfo=UTC)
            price = req.entry_price or close[1]
            basis = (
                f"your price, bought {_fmt_day(req.entry_date)}"
                if req.entry_price
                else f"close on {_fmt_day(close[0])} {close[0].year}"
            )
        else:
            entry_at = now
            live = await self._live([inst])
            if req.entry_price:
                price, basis = req.entry_price, "your price"
            elif inst.instrument_key in live:
                price, _, how = live[inst.instrument_key]
                if how == "last close":  # market closed: the quote is the last session's close
                    basis = f"last close, added {_fmt_day(today)}"
                else:
                    basis = f"{how} price at {to_ist(now):%H:%M} on {_fmt_day(today)}"
            else:
                series = await self._points(inst)
                if not series:
                    raise AppError(f"No price available for {inst.symbol}.", status_code=422)
                price = series[-1][1]
                basis = f"last close ({_fmt_day(series[-1][0])})"
        if req.quantity:
            qty = req.quantity
        elif req.amount:
            qty = math.floor(req.amount / price)
            if qty < 1:
                raise AppError(
                    f"Rs {req.amount:,.0f} buys no whole share of {inst.symbol} "
                    f"at Rs {price:,.2f}.",
                    status_code=422,
                )
        else:
            raise AppError("Give a quantity or an amount.", status_code=422)
        self._db.execute(
            "INSERT INTO tracked_positions (id, portfolio_id, instrument_key, quantity, "
            "entry_price, entry_at, entry_basis) VALUES (?, ?, ?, ?, ?, ?, ?)",
            [uuid.uuid4().hex[:12], pid, inst.instrument_key, qty, price, entry_at, basis],
        )
        # Keep the stock researched so later reviews can show what changed.
        self._research.enqueue(inst.instrument_key)

    # --- prices ------------------------------------------------------------------------

    async def _points(self, inst: Instrument) -> list[tuple[date, float]]:
        a = await self._portfolio._asset(inst, divs=False)
        return [(session_date(t // 86400), c) for t, c in a.series.pairs]

    async def _live(self, insts: list[Instrument]) -> dict[str, tuple[float, float | None, str]]:
        """key -> (last price, change today, basis) from live quotes."""
        out: dict[str, tuple[float, float | None, str]] = {}
        with contextlib.suppress(AppError):
            quotes = await self._data.quotes_for(insts)
            for k, q in quotes.items():
                if q.ltp:
                    basis = "live" if q.freshness == "live" else q.freshness.replace("_", " ")
                    out[k] = (q.ltp, q.change, basis)
        return out

    # --- portfolios --------------------------------------------------------------------

    async def summaries(self) -> list[PortfolioSummaryRow]:
        rows = self._db.fetchall("SELECT id FROM tracked_portfolios ORDER BY created_at")
        out = []
        for (pid,) in rows:
            p = await self.portfolio(pid)
            out.append(
                PortfolioSummaryRow(
                    id=p.id,
                    name=p.name,
                    created_at=p.created_at,
                    last_viewed_at=p.last_viewed_at,
                    positions=len(p.positions),
                    value=p.value,
                    cost=p.cost,
                    pnl=p.pnl,
                    pnl_pct=p.pnl_pct,
                    day_change_pct=p.day_change_pct,
                    kind=p.kind,
                    cash=p.cash,
                    account_value=p.account_value,
                    account_return=p.account_return,
                )
            )
        return out

    async def portfolio(self, pid: str) -> TrackedPortfolio:
        pid_, name, created, viewed = self._row(pid)
        kind, starting_cash, cash, plan = self.account(pid)
        rows = self._positions(pid)
        extra = {
            r[0]: r[1:]
            for r in self._db.fetchall(
                "SELECT id, coalesce(charges, 0), reason, tag FROM tracked_positions "
                "WHERE portfolio_id = ?",
                [pid],
            )
        }
        found = self._instruments.get_many([r[1] for r in rows])
        insts = [found[r[1]] for r in rows if r[1] in found]
        live = await self._live(insts) if insts else {}
        positions: list[Position] = []
        day_total = 0.0
        day_known = False
        for row_id, key, qty, entry, at, basis in rows:
            inst = found.get(key)
            if inst is None:
                continue
            px = live.get(key)
            price, price_basis, change = (px[0], px[2], px[1]) if px else (None, None, None)
            if price is None:
                with contextlib.suppress(AppError):
                    pts = await self._points(inst)
                    if pts:
                        price, price_basis = pts[-1][1], f"close {_fmt_day(pts[-1][0])}"
            value = qty * price if price else None
            cost = qty * entry
            # Today's change counts only for positions held before today's session.
            held_before_today = to_ist(_as_utc(at)).date() < to_ist(datetime.now(UTC)).date()
            if change is not None and held_before_today:
                day_total += qty * change
                day_known = True
            prev = price - change if price is not None and change is not None else None
            positions.append(
                Position(
                    id=row_id,
                    symbol=inst.symbol,
                    name=inst.name,
                    instrument_key=key,
                    sector=self._instruments.industry_of(inst.isin) or "Unclassified",
                    quantity=float(qty),
                    entry_price=float(entry),
                    entry_at=_as_utc(at),
                    entry_basis=basis,
                    price=price,
                    price_basis=price_basis,
                    value=value,
                    cost=cost,
                    pnl=value - cost if value is not None else None,
                    pnl_pct=(value - cost) / cost if value is not None and cost else None,
                    day_change=qty * change if change is not None else None,
                    day_change_pct=change / prev if change is not None and prev else None,
                    weight=None,
                    charges=float(extra.get(row_id, (0.0,))[0] or 0.0),
                    reason=extra.get(row_id, (0, None))[1],
                    tag=extra.get(row_id, (0, None, None))[2],
                    break_even=(
                        break_even(float(entry), float(qty), plan) if kind == "paper" else None
                    ),
                )
            )
        total = sum(p.value for p in positions if p.value is not None) or None
        for p in positions:
            p.weight = p.value / total if total and p.value is not None else None
        cost = sum(p.cost for p in positions)
        priced_cost = sum(p.cost for p in positions if p.value is not None)
        pnl = total - priced_cost if total is not None else None
        base = (total or 0) - day_total
        account_value = account_return = None
        reserved = realized = charges_paid = 0.0
        if kind == "paper":
            reserved = self.reserved_cash(pid)
            realized, sell_charges = self._db.fetchone(
                "SELECT coalesce(sum((sell_price - buy_price) * quantity - buy_charges - "
                "sell_charges), 0), coalesce(sum(sell_charges + buy_charges), 0) "
                "FROM paper_trades WHERE portfolio_id = ?",
                [pid],
            )
            charges_paid = float(sell_charges) + sum(p.charges for p in positions)
            account_value = float(cash or 0) + (total or 0.0)
            account_return = account_value / starting_cash - 1 if starting_cash else None
        return TrackedPortfolio(
            id=pid_,
            name=name,
            created_at=_as_utc(created),
            last_viewed_at=_as_utc(viewed) if viewed else None,
            positions=positions,
            value=total,
            cost=cost,
            pnl=pnl,
            pnl_pct=pnl / priced_cost if pnl is not None and priced_cost else None,
            day_change=day_total if day_known else None,
            day_change_pct=day_total / base if day_known and base > 0 else None,
            priced_at=datetime.now(UTC),
            kind=kind,
            plan=plan,
            starting_cash=starting_cash,
            cash=cash,
            reserved=reserved,
            account_value=account_value,
            account_return=account_return,
            realized=float(realized),
            charges_paid=charges_paid,
        )

    def reserved_cash(self, pid: str) -> float:
        """Cash set aside for open buy orders: their value at the limit (or last known) price
        plus charges, so two orders cannot spend the same money."""
        row = self._db.fetchone(
            "SELECT coalesce(sum(quantity * coalesce(limit_price, trigger_price, est_price, 0)), "
            "0) FROM paper_orders WHERE portfolio_id = ? AND side = 'BUY' AND status = 'OPEN'",
            [pid],
        )
        value = float(row[0]) if row else 0.0
        return value * 1.002  # charges on a delivery buy stay below 0.2%

    # --- review: what happened and why --------------------------------------------------

    def _period_start(
        self, period: Period, created: datetime, viewed: datetime | None, first_entry: datetime
    ) -> datetime:
        now = datetime.now(UTC)
        if period == "today":
            ist = to_ist(now)
            return datetime(ist.year, ist.month, ist.day, tzinfo=ist.tzinfo).astimezone(UTC)
        if period == "1w":
            return now - timedelta(days=7)
        if period == "1m":
            return now - timedelta(days=30)
        if period == "last_visit" and viewed is not None:
            return viewed
        return min(created, first_entry)

    async def review(self, pid: str, period: Period, narrate: bool = False) -> Review:
        _, name, created, viewed = self._row(pid)
        created, viewed = _as_utc(created), _as_utc(viewed) if viewed else None
        rows = self._positions(pid)
        now = datetime.now(UTC)
        today = to_ist(now).date()
        if not rows:
            raise AppError("Add stocks to this portfolio first.", status_code=422)
        first_entry = min(_as_utc(r[4]) for r in rows)
        start = self._period_start(period, created, viewed, first_entry)
        if period == "last_visit" and viewed is None:
            period_label = "Since you started (first visit)"
        else:
            period_label = PERIOD_LABEL[period]
        cutoff = T.start_cutoff(start)
        found = self._instruments.get_many([r[1] for r in rows])
        insts = [found[r[1]] for r in rows if r[1] in found]
        live = await self._live(insts)
        gaps: list[str] = []

        nifty_inst = self._index("NIFTY")
        nifty_pts: list[tuple[date, float]] = []
        nifty_now = None
        if nifty_inst:
            with contextlib.suppress(AppError):
                nifty_pts = await self._points(nifty_inst)
            nifty_live = await self._live([nifty_inst])
            nifty_now = nifty_live.get(nifty_inst.instrument_key, (None,))[0]
        market_ret = T.period_return(nifty_pts, cutoff, nifty_now) if nifty_pts else None
        # The session whose close the period starts from (the cutoff may be a holiday).
        start_close = T.close_on_or_before(nifty_pts, cutoff) if nifty_pts else None
        start_day = start_close[0] if start_close else cutoff
        if market_ret is None:
            gaps.append("NIFTY 50 history unavailable; market comparison left out.")

        series: dict[str, list[tuple[date, float]]] = {}
        qty: dict[str, float] = {}
        entries: dict[str, date] = {}
        stocks: list[StockReview] = []
        start_value = end_value = 0.0

        async def one(row) -> StockReview | None:
            row_id, key, q, entry_price, entry_at, basis = row
            inst = found.get(key)
            if inst is None:
                gaps.append(f"{key} is no longer in the instrument master.")
                return None
            entry_at = _as_utc(entry_at)
            try:
                pts = await self._points(inst)
            except AppError as exc:
                gaps.append(f"{inst.symbol}: price history unavailable ({exc.message}).")
                return None
            series[row_id] = pts
            qty[row_id] = float(q)
            entries[row_id] = to_ist(entry_at).date()
            end = live.get(key, (pts[-1][1] if pts else None,))[0]
            if not end:
                return None
            entered_in_period = entry_at > start
            if entered_in_period:
                s_price, s_basis, s_cut = (
                    float(entry_price),
                    f"your entry ({basis})",
                    T.start_cutoff(entry_at),
                )
            else:
                c = T.close_on_or_before(pts, cutoff)
                if c is None:
                    gaps.append(f"{inst.symbol}: no price at the start of the period.")
                    return None
                s_price, s_basis, s_cut = c[1], f"close on {_fmt_day(c[0])}", cutoff
            ret = end / s_price - 1
            contribution = float(q) * (end - s_price)
            mkt = T.period_return(nifty_pts, s_cut, nifty_now) if nifty_pts else None
            sector_label, sector_ret = await self._sector_return(inst, s_cut)
            specific = (
                ret - sector_ret
                if sector_ret is not None
                else (ret - mkt if mkt is not None else None)
            )
            driver = T.driver_of(ret, sector_ret, mkt)
            moves = [
                Move(date=d, change_pct=r, live=lv)
                for d, r, lv in T.big_moves(pts, s_cut, live.get(key, (None,))[0], today)
            ]
            headlines = await self._headlines(
                inst, start if not entered_in_period else entry_at, moves
            )
            dividends = await self._dividends(inst.symbol, s_cut)
            research = self._research_shift(key, start if not entered_in_period else entry_at)
            events = self._events(inst.symbol, start)
            stock = StockReview(
                symbol=inst.symbol,
                name=inst.name,
                sector=self._instruments.industry_of(inst.isin) or "Unclassified",
                quantity=float(q),
                start_price=s_price,
                start_basis=s_basis,
                end_price=end,
                return_pct=ret,
                contribution=contribution,
                contribution_share=0.0,
                market_return=mkt,
                sector_label=sector_label,
                sector_return=sector_ret,
                stock_specific=specific,
                driver=driver,  # type: ignore[arg-type]
                moves=moves,
                headlines=headlines,
                dividends=dividends,
                research=research,
                events=events,
                explanation="",
            )
            stock.explanation = self._explain(stock)
            return stock

        results = await asyncio.gather(*(one(r) for r in rows))
        for s in results:
            if s is None:
                continue
            stocks.append(s)
            start_value += s.quantity * s.start_price
            end_value += s.quantity * s.end_price
        total_abs = sum(abs(s.contribution) for s in stocks) or 1.0
        for s in stocks:
            s.contribution_share = s.contribution / total_abs
        stocks.sort(key=lambda s: -abs(s.contribution))
        change = end_value - start_value
        change_pct = change / start_value if start_value else None
        # What the same money would have done in the index over each stock's own dates.
        late = any(s.start_basis.startswith("your entry") for s in stocks)
        if stocks and all(s.market_return is not None for s in stocks):
            market_part = sum(s.quantity * s.start_price * s.market_return for s in stocks)
            bench = market_part / start_value if start_value else market_ret
        else:
            market_part, bench = None, market_ret
        selection = change - market_part if market_part is not None else None
        bench_label = "NIFTY 50 over the same dates" if late else "NIFTY 50"

        headline, points, facts = self._summarise(
            stocks,
            period_label,
            change,
            change_pct,
            bench,
            bench_label,
            market_part,
            selection,
            start_day,
        )
        if (
            stocks
            and all(s.start_price == s.end_price for s in stocks)
            and not nifty_moved(nifty_pts, start_day, nifty_now)
        ):
            # Nothing has traded since the period began (a weekend, a holiday, the same evening).
            headline = (
                f"{period_label}: no change. The market has not traded since the close on "
                f"{_fmt_day(start_day)}."
            )
            points = [p for p in points if not p.startswith("Tracking the NIFTY 50")]
        value_series, cost_series = self._history(series, qty, entries, rows, end_value)
        review = Review(
            portfolio_id=pid,
            period=period,
            period_label=period_label,
            start=start,
            start_basis=f"Prices from the close on {_fmt_day(start_day)} {start_day.year}, or your "
            "entry price for stocks added later",
            end=now,
            start_value=start_value,
            end_value=end_value,
            change=change,
            change_pct=change_pct,
            benchmark_label=bench_label,
            benchmark_return=bench,
            market_part=market_part,
            selection_part=selection,
            headline=headline,
            points=points,
            stocks=stocks,
            value_series=value_series,
            cost_series=cost_series,
            facts=facts,
            gaps=gaps,
            computed_at=now,
        )
        if narrate and self._narrate:
            with contextlib.suppress(AppError):
                review.narrative = await self._narrate(headline, points, facts)
        return review

    async def explain_stock(self, inst: Instrument, since: datetime) -> StockReview | None:
        """One stock's move since ``since`` with the evidence a portfolio review gives: the
        market, sector and company parts, its big days, headlines, dividends and research
        changes. Reported for one share. None when there is no price at the start."""
        pts = await self._points(inst)
        cutoff = T.start_cutoff(since)
        start = T.close_on_or_before(pts, cutoff)
        live = await self._live([inst])
        end = live.get(inst.instrument_key, (pts[-1][1] if pts else None,))[0]
        if start is None or not end:
            return None
        mkt = None
        nifty = self._index("NIFTY")
        if nifty:
            with contextlib.suppress(AppError):
                nifty_pts = await self._points(nifty)
                nifty_live = await self._live([nifty])
                mkt = T.period_return(
                    nifty_pts, cutoff, nifty_live.get(nifty.instrument_key, (None,))[0]
                )
        ret = end / start[1] - 1
        sector_label, sector_ret = await self._sector_return(inst, cutoff)
        if sector_ret is not None:
            specific = ret - sector_ret
        else:
            specific = ret - mkt if mkt is not None else None
        today = to_ist(datetime.now(UTC)).date()
        moves = [
            Move(date=d, change_pct=r, live=lv) for d, r, lv in T.big_moves(pts, cutoff, end, today)
        ]
        stock = StockReview(
            symbol=inst.symbol,
            name=inst.name,
            sector=self._instruments.industry_of(inst.isin) or "Unclassified",
            quantity=1.0,
            start_price=start[1],
            start_basis=f"close on {_fmt_day(start[0])}",
            end_price=end,
            return_pct=ret,
            contribution=end - start[1],
            contribution_share=0.0,
            market_return=mkt,
            sector_label=sector_label,
            sector_return=sector_ret,
            stock_specific=specific,
            driver=T.driver_of(ret, sector_ret, mkt),  # type: ignore[arg-type]
            moves=moves,
            headlines=await self._headlines(inst, since, moves),
            dividends=await self._dividends(inst.symbol, cutoff),
            research=self._research_shift(inst.instrument_key, since),
            events=self._events(inst.symbol, since),
            explanation="",
        )
        stock.explanation = self._explain(stock)
        return stock

    # --- review parts -------------------------------------------------------------------

    def _index(self, symbol: str) -> Instrument | None:
        try:
            return self._instruments.by_symbol(symbol, "NSE_INDEX")
        except NotFound:
            return None

    async def _sector_return(
        self, inst: Instrument, cutoff: date
    ) -> tuple[str | None, float | None]:
        industry = self._instruments.industry_of(inst.isin)
        mapped = SECTOR_INDEX.get(industry or "")
        if not mapped:
            return None, None
        index = self._index(mapped[1])
        if index is None:
            return mapped[0], None
        try:
            pts = await self._points(index)
        except AppError:
            return mapped[0], None
        live = await self._live([index])
        return mapped[0], T.period_return(pts, cutoff, live.get(index.instrument_key, (None,))[0])

    async def _headlines(
        self, inst: Instrument, since: datetime, moves: list[Move]
    ) -> list[Headline]:
        try:
            items, _ = await self._data.headlines(inst)
        except AppError:
            return []
        out: list[Headline] = []
        floor = since - timedelta(days=1)
        for item in items:
            if item.published_at is None or item.published_at < floor:
                continue
            day = to_ist(item.published_at).date()
            near = next((m.date for m in moves if abs((m.date - day).days) <= 1), None)
            score = score_headline(item.title).score
            tone = "positive" if score > 0 else "negative" if score < 0 else "neutral"
            out.append(
                Headline(
                    title=item.title,
                    link=item.link,
                    publisher=item.publisher,
                    published_at=item.published_at,
                    tone=tone,  # type: ignore[arg-type]
                    near_move=near,
                )
            )
        # Headlines around the big moves first, then the most opinionated, then the newest.
        out.sort(
            key=lambda h: (
                h.near_move is None,
                h.tone == "neutral",
                -(h.published_at.timestamp() if h.published_at else 0),
            )
        )
        return out[:4]

    async def _dividends(self, symbol: str, cutoff: date) -> list[Dividend]:
        try:
            rows = await self._data.dividends(symbol)
        except AppError:
            return []
        return [Dividend(ex_date=d, amount=a) for d, a in rows if d > cutoff]

    def _research_shift(self, key: str, since: datetime) -> ResearchShift | None:
        latest = self._research.latest(key)
        if latest is None:
            return None
        before = self._research.report_at(key, since)
        if before is None or before.computed_at >= latest.computed_at:
            return None
        diff = diff_reports(before, latest)
        if not diff.items:
            return None
        return ResearchShift(
            before_signal=before.composite.signal,
            after_signal=latest.composite.signal,
            before_score=before.composite.score,
            after_score=latest.composite.score,
            summary=diff.summary,
            since=before.computed_at,
        )

    def _events(self, symbol: str, since: datetime) -> list[str]:
        rows = self._db.fetchall(
            "SELECT title FROM events WHERE symbol = ? AND created_at >= ? "
            "AND kind IN ('results', 'research', 'market') ORDER BY created_at",
            [symbol, since],
        )
        return [r[0] for r in rows][:4]

    @staticmethod
    def _explain(s: StockReview) -> str:
        parts = [f"{s.symbol} {pct(s.return_pct, True)} ({_rupees(s.contribution)})."]
        m = s.market_return
        if abs(s.return_pct) < 0.0005 and (m is None or abs(m) < 0.0005):
            parts = [f"{s.symbol} is unchanged from {s.start_basis}."]
        elif m is not None:
            text = f"Over the same dates the NIFTY 50 {'rose' if m >= 0 else 'fell'} {pct(abs(m))}"
            if s.sector_return is not None:
                gap = s.sector_return - m
                if abs(gap) < SMALL:
                    text += f" and {s.sector_label} moved with it"
                else:
                    word = "beat" if gap > 0 else "lagged"
                    text += f" and {s.sector_label} {word} it by {_points(gap)}"
            own = s.stock_specific
            if own is not None:
                ref = "its sector" if s.sector_return is not None else "the market"
                if abs(own) < SMALL:
                    text += f"; {s.symbol} moved in line with {ref}"
                else:
                    word = "better" if own > 0 else "worse"
                    text += f"; {s.symbol} did {_points(own)} {word} than {ref}"
            parts.append(text + ".")
            if s.driver in DRIVER_TEXT:
                parts.append(f"Largest factor: {DRIVER_TEXT[s.driver]}.")
        if s.moves:
            biggest = max(s.moves, key=lambda m: abs(m.change_pct))
            when = "today so far" if biggest.live else f"on {_fmt_day(biggest.date)}"
            text = f"Biggest move {pct(biggest.change_pct, True)} {when}"
            near = [h for h in s.headlines if h.near_move == biggest.date]
            if near:
                text += f"; reported around then: “{near[0].title}”"
            parts.append(text + ".")
        if s.dividends:
            d = s.dividends[0]
            parts.append(
                f"Went ex-dividend on {_fmt_day(d.ex_date)} (Rs {d.amount:g} a share), which "
                "lowers the price by about that amount."
            )
        if s.research:
            parts.append(f"Research: {s.research.summary}")
        return " ".join(parts)

    def _summarise(
        self, stocks, label, change, change_pct, bench, bench_label, market_part, selection, cutoff
    ):
        book = FactBook()
        points: list[str] = []
        direction = "up" if change > 0 else "down" if change < 0 else "flat"
        headline = f"{label}: your portfolio is {direction} {_rupees(change).lstrip('+')}"
        if change_pct is not None:
            headline += f" ({pct(change_pct, True)})"
        if bench is not None:
            if bench_label == "NIFTY 50":
                headline += f", while the NIFTY 50 moved {pct(bench, True)}"
            else:
                headline += f"; the same money in the NIFTY 50 would have moved {pct(bench, True)}"
        headline += "."
        book.add(
            f"{label} (from the close on {_fmt_day(cutoff)}): portfolio {_rupees(change)} "
            f"({pct(change_pct, True)}); {bench_label} {pct(bench, True)}.",
            SOURCE,
            "measured",
        )
        if market_part is not None and selection is not None:
            points.append(
                f"Tracking the NIFTY 50 over the same dates would have made "
                f"{_rupees(market_part)}; the difference, {_rupees(selection)}, came from which "
                "stocks you hold."
            )
            book.add(points[-1], SOURCE, "estimate")
        gainers = [s for s in stocks if s.contribution > 0]
        losers = [s for s in stocks if s.contribution < 0]
        if gainers:
            top = max(gainers, key=lambda s: s.contribution)
            points.append(
                f"{top.symbol} added the most ({_rupees(top.contribution)}, "
                f"{pct(top.return_pct, True)})."
            )
        if losers:
            worst = min(losers, key=lambda s: s.contribution)
            points.append(
                f"{worst.symbol} held it back most ({_rupees(worst.contribution)}, "
                f"{pct(worst.return_pct, True)})."
            )
        for s in stocks:
            book.add(s.explanation, SOURCE, "measured")
            for h in s.headlines[:2]:
                when = f"{to_ist(h.published_at):%d %b}" if h.published_at else "undated"
                book.add(
                    f"{s.symbol} headline ({h.publisher}, {when}): {h.title}",
                    "Google News search",
                    "observed",
                    h.published_at,
                )
        shifts = [
            s for s in stocks if s.research and s.research.before_signal != s.research.after_signal
        ]
        for s in shifts[:2]:
            points.append(
                f"Research on {s.symbol} moved from "
                f"{SIGNAL_LABEL.get(s.research.before_signal or '', 'n/a')} "
                f"to {SIGNAL_LABEL[s.research.after_signal]}."
            )
        return headline, points, book.facts

    @staticmethod
    def _history(series, qty, entries, rows, end_value):
        """Daily value of the positions held each day and the money put in, from the first
        entry onwards."""
        if not series:
            return [], []
        first = min(entries.values())
        days = sorted({d for pts in series.values() for d, _ in pts if d >= first})
        cost_by_key = {r[0]: float(r[2]) * float(r[3]) for r in rows}  # per position
        value, cost = [], []
        for d in days:
            t = (
                datetime(d.year, d.month, d.day, tzinfo=UTC) - datetime(1970, 1, 1, tzinfo=UTC)
            ).days
            stamp = t * 86400
            value.append(
                CurvePoint(time=stamp, value=round(T.holdings_value(series, qty, entries, d), 2))
            )
            cost.append(
                CurvePoint(
                    time=stamp,
                    value=round(
                        sum(c for k, c in cost_by_key.items() if k in entries and entries[k] <= d),
                        2,
                    ),
                )
            )
        today = to_ist(datetime.now(UTC)).date()
        if days and days[-1] < today:
            stamp = (
                datetime(today.year, today.month, today.day, tzinfo=UTC)
                - datetime(1970, 1, 1, tzinfo=UTC)
            ).days * 86400
            value.append(CurvePoint(time=stamp, value=round(end_value, 2)))
            total_cost = sum(c for k, c in cost_by_key.items() if k in entries)
            cost.append(CurvePoint(time=stamp, value=round(total_cost, 2)))
        return value, cost
