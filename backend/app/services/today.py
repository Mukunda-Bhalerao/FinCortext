"""The daily feed: gathers what the app knows about the user's accounts, watchlist, IPOs and
strategies into a snapshot, and lets the rules in ``tools.nudges`` decide what is worth
attention. Every source is optional: when one is unavailable the feed says so and carries on.
"""

import asyncio
import logging
import time
from datetime import UTC, datetime, timedelta

from app.db import Database
from app.errors import AppError
from app.schemas.chat import TodayFeed
from app.services.candles import CandleService
from app.services.ipo import IpoService
from app.services.market import MarketService
from app.services.session import SessionClock
from app.services.strategy import StrategyService
from app.services.tracker import TrackerService
from app.tools import nudges as N
from app.tools.candles import trailing_range
from app.tools.market_hours import to_ist
from app.tools.technicals import rsi

log = logging.getLogger(__name__)

CACHE_SECONDS = 45.0
IPO_WAIT = 4.0  # seconds to wait for IPO data before building the feed without it
IPO_REUSE = 600.0  # seconds an IPO overview is reused before asking again
WATCH_LIMIT = 20


class TodayService:
    def __init__(
        self,
        db: Database,
        market: MarketService,
        candles: CandleService,
        tracker: TrackerService,
        ipo: IpoService,
        strategies: StrategyService,
        clock: SessionClock,
    ):
        self._db = db
        self._market = market
        self._candles = candles
        self._tracker = tracker
        self._ipo = ipo
        self._strategies = strategies
        self._clock = clock
        self._cached: tuple[float, TodayFeed] | None = None
        self._ipo_task: asyncio.Task | None = None
        self._ipo_at = 0.0

    # --- snapshot parts --------------------------------------------------------------------

    def _count(self, sql: str, params: list) -> int:
        row = self._db.fetchone(sql, params)
        return int(row[0]) if row else 0

    async def _accounts(self) -> list[N.Account]:
        out: list[N.Account] = []
        rows = self._db.fetchall(
            "SELECT id FROM tracked_portfolios WHERE coalesce(kind, 'tracking') = 'paper' "
            "ORDER BY created_at"
        )
        for (pid,) in rows:
            p = await self._tracker.portfolio(pid)
            stops = {
                r[0]
                for r in self._db.fetchall(
                    "SELECT DISTINCT instrument_key FROM paper_orders WHERE portfolio_id = ? "
                    "AND status = 'OPEN' AND side = 'SELL' AND kind = 'SL'",
                    [pid],
                )
            }
            by_symbol: dict[str, list] = {}
            for pos in p.positions:
                by_symbol.setdefault(pos.symbol, []).append(pos)
            holdings = []
            for symbol, lots in by_symbol.items():
                priced = [x for x in lots if x.value is not None]
                value = sum(x.value for x in priced) if priced else None
                paid = sum(x.cost + x.charges for x in priced)
                holdings.append(
                    N.Holding(
                        symbol=symbol,
                        value=value,
                        pnl_pct=(value - paid) / paid if value is not None and paid else None,
                        has_stop=any(x.instrument_key in stops for x in lots),
                    )
                )
            out.append(
                N.Account(
                    id=pid,
                    name=p.name,
                    value=p.account_value or 0.0,
                    cash=p.cash or 0.0,
                    orders_total=self._count(
                        "SELECT count(*) FROM paper_orders WHERE portfolio_id = ?", [pid]
                    ),
                    open_orders=self._count(
                        "SELECT count(*) FROM paper_orders WHERE portfolio_id = ? "
                        "AND status = 'OPEN'",
                        [pid],
                    ),
                    closed_trades=self._count(
                        "SELECT count(*) FROM paper_trades WHERE portfolio_id = ?", [pid]
                    ),
                    reasons_written=self._count(
                        "SELECT count(*) FROM paper_orders WHERE portfolio_id = ? AND "
                        "source = 'you' AND reason IS NOT NULL AND reason <> ''",
                        [pid],
                    ),
                    holdings=holdings,
                )
            )
        return out

    async def _watch(self) -> tuple[list[N.Watch], int]:
        items = [i for i in await self._market.watchlist() if i.instrument.segment == "NSE_EQ"]
        slots = asyncio.Semaphore(6)
        now = datetime.now(UTC)

        async def one(item) -> N.Watch:
            q = item.quote
            w = N.Watch(symbol=item.instrument.symbol)
            if q and q.change is not None and q.prev_close:
                w.day_pct = q.change / q.prev_close
            async with slots:
                try:
                    series = await self._candles.series(item.instrument.instrument_key, "1D")
                except AppError:
                    return w
            candles = series.candles
            price = q.ltp if q and q.ltp else (candles[-1].close if candles else None)
            rng = trailing_range(candles, now)
            if rng and price:
                high, low = max(rng[0], price), min(rng[1], price)
                w.from_high = price / high - 1 if high > 0 else None
                w.from_low = price / low - 1 if low > 0 else None
            w.rsi = rsi([c.close for c in candles]) if len(candles) > 20 else None
            return w

        watch = await asyncio.gather(*(one(i) for i in items[:WATCH_LIMIT]))
        return list(watch), len(items)

    async def _ipos(self, gaps: list[str]) -> list[N.OpenIpo]:
        task = self._ipo_task
        if (
            task is not None
            and task.done()
            and not task.cancelled()
            and task.exception() is None
            and time.monotonic() - self._ipo_at < IPO_REUSE
        ):
            return self._open_ipos(task.result())
        if task is None or task.done():
            self._ipo_task = task = asyncio.create_task(self._ipo.overview())
            self._ipo_at = time.monotonic()
        try:
            overview = await asyncio.wait_for(asyncio.shield(task), IPO_WAIT)
        except TimeoutError:
            gaps.append("IPO data is still loading; IPO items will appear shortly.")
            return []
        except AppError as exc:
            gaps.append(f"IPO data unavailable: {exc.message}")
            return []
        return self._open_ipos(overview)

    @staticmethod
    def _open_ipos(overview) -> list[N.OpenIpo]:
        return [
            N.OpenIpo(
                symbol=i.symbol,
                company=i.company,
                closes=i.close_date,
                qib=i.subscription.qib if i.subscription else None,
                board=i.board,
            )
            for i in overview.open
        ]

    # --- public ----------------------------------------------------------------------------

    async def snapshot(self, gaps: list[str]) -> tuple[N.Snapshot, int]:
        now = datetime.now(UTC)
        today = to_ist(now).date()
        s = N.Snapshot(today=today, market_open=self._clock.state()[0] == "open")
        s.accounts = await self._accounts()
        watching = 0
        try:
            s.watch, watching = await self._watch()
        except AppError as exc:
            gaps.append(f"Watchlist prices unavailable: {exc.message}")
            watching = len(self._market.watchlist_keys())
        s.research_changes = [
            (r[0], r[1])
            for r in self._db.fetchall(
                "SELECT symbol, title FROM events WHERE kind = 'research' AND symbol IS NOT NULL "
                "AND created_at >= ? ORDER BY created_at DESC LIMIT 5",
                [now - timedelta(hours=72)],
            )
        ]
        s.ipos = await self._ipos(gaps)
        saved = self._strategies.all()
        s.strategies_saved = len(saved)
        s.strategy_notes = [
            (x.name, x.last_note)
            for x in saved
            if x.active and x.last_run == today and x.last_note and "order placed" in x.last_note
        ]
        try:
            sectors = await self._market.sectors()
            priced = [i for i in sectors if i.quote and i.quote.change is not None]
            s.sectors_total = len(priced)
            s.sectors_up = sum(1 for i in priced if (i.quote.change or 0) > 0)
        except AppError as exc:
            gaps.append(f"Sector data unavailable: {exc.message}")
        return s, watching

    async def feed(self) -> TodayFeed:
        if self._cached and time.monotonic() - self._cached[0] < CACHE_SECONDS:
            return self._cached[1]
        gaps: list[str] = []
        snap, watching = await self.snapshot(gaps)
        feed = TodayFeed(
            nudges=N.build_nudges(snap),
            progress=N.build_progress(snap, watching),
            gaps=gaps,
            generated_at=datetime.now(UTC),
        )
        self._cached = (time.monotonic(), feed)
        return feed

    def invalidate(self) -> None:
        self._cached = None

    async def aclose(self) -> None:
        if self._ipo_task is not None:
            self._ipo_task.cancel()
