"""Notices changes worth a user's attention and records them as events.

Every ten minutes it checks the watchlist and holdings for research views that changed, price
moves that are large for that stock, drift between holdings and the chosen plan, risk piling
into one stock, a new best diversifier, failing data sources and fresh validation results.
Each event carries the facts it is based on and is stored once (a stable id per day or per
change), so restarts do not repeat it.
"""

import asyncio
import contextlib
import json
import logging
import math
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from app.db import Database, _as_utc
from app.errors import AppError
from app.schemas.insights import Fact
from app.services.insights import ENGINE, RESEARCH, pct
from app.services.instruments import InstrumentService
from app.services.monitor import SourceMonitor
from app.services.portfolio import PortfolioService
from app.services.quotes import QuoteService
from app.services.research import ResearchService
from app.services.signal_lab import SignalLab
from app.tools import technicals as ta
from app.tools.market_hours import IST, to_ist

log = logging.getLogger(__name__)

INTERVAL = 10 * 60
MOVE_FLOOR = 0.03  # a daily move must be at least 3% ...
MOVE_SIGMA = 2.5  # ... and at least 2.5 typical daily moves
DRIFT_BAND = 0.05
CONCENTRATION = 0.5
KEEP_DAYS = 60
DAILY_CAP = 6  # new non-urgent alerts per IST day
SEVERITY_RANK = {"low": 0, "medium": 1, "high": 2}
# Days before another alert of the same kind for the same stock (or the portfolio).
COOLDOWN = {"research": 2, "market": 1, "portfolio": 3, "opportunity": 7, "data": 1, "results": 30}
BASE_PRIORITY = {"high": 80.0, "medium": 50.0, "low": 20.0}


class Watcher:
    def __init__(
        self,
        db: Database,
        instruments: InstrumentService,
        quotes: QuoteService,
        research: ResearchService,
        portfolio: PortfolioService,
        lab: SignalLab,
        monitor: SourceMonitor,
        watchlist_keys: Callable[[], list[str]],
    ):
        self._db = db
        self._instruments = instruments
        self._quotes = quotes
        self._research = research
        self._portfolio = portfolio
        self._lab = lab
        self._monitor = monitor
        self._watchlist_keys = watchlist_keys
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    async def _loop(self) -> None:
        await self._instruments.ready.wait()
        await asyncio.sleep(30)  # let the first research and analysis runs settle
        while True:
            try:
                await self.check()
            except Exception:  # one bad check must not stop the watcher
                log.exception("watcher check failed")
            await asyncio.sleep(INTERVAL)

    # --- storage -----------------------------------------------------------------------

    def add(
        self,
        eid: str,
        kind: str,
        severity: str,
        title: str,
        body: str,
        facts: list[Fact],
        symbol: str | None = None,
        boost: float = 0.0,
    ) -> bool:
        """Store an event unless it repeats one already stored, falls inside the cooldown for
        its kind and stock (a more severe alert still gets through), or today's quota of
        non-urgent alerts is used up."""
        if self._db.fetchone("SELECT 1 FROM events WHERE id = ?", [eid]):
            return False
        now = datetime.now(UTC)
        recent = self._db.fetchall(
            "SELECT severity FROM events WHERE kind = ? AND symbol IS NOT DISTINCT FROM ? "
            "AND created_at > ?",
            [kind, symbol, now - timedelta(days=COOLDOWN.get(kind, 1))],
        )
        if any(SEVERITY_RANK[r[0]] >= SEVERITY_RANK[severity] for r in recent):
            return False
        if severity != "high":
            start = datetime.combine(to_ist(now).date(), datetime.min.time(), tzinfo=IST)
            today = self._db.fetchone(
                "SELECT count(*) FROM events WHERE created_at >= ? AND severity != 'high'",
                [start],
            )
            if today and today[0] >= DAILY_CAP:
                return False
        self._db.execute(
            "INSERT INTO events (id, kind, severity, symbol, title, body, facts, created_at, seen, "
            "priority) VALUES (?, ?, ?, ?, ?, ?, ?, ?, FALSE, ?)",
            [
                eid,
                kind,
                severity,
                symbol,
                title,
                body,
                json.dumps([f.model_dump(mode="json") for f in facts]),
                now,
                BASE_PRIORITY[severity] + boost,
            ],
        )
        return True

    def recent(self, limit: int = 40) -> tuple[list[dict], int]:
        rows = self._db.fetchall(
            "SELECT id, kind, severity, symbol, title, body, facts, created_at, seen FROM events "
            "ORDER BY seen, CAST(created_at AS DATE) DESC, priority DESC, created_at DESC LIMIT ?",
            [limit],
        )
        unread = self._db.fetchone("SELECT count(*) FROM events WHERE NOT seen")
        out = [
            {
                "id": r[0],
                "kind": r[1],
                "severity": r[2],
                "symbol": r[3],
                "title": r[4],
                "body": r[5],
                "facts": json.loads(r[6]),
                "created_at": _as_utc(r[7]),
                "seen": bool(r[8]),
            }
            for r in rows
        ]
        return out, int(unread[0]) if unread else 0

    def mark_seen(self, ids: list[str] | None = None) -> None:
        if ids:
            for i in ids:
                self._db.execute("UPDATE events SET seen = TRUE WHERE id = ?", [i])
        else:
            self._db.execute("UPDATE events SET seen = TRUE WHERE NOT seen")

    # --- checks ------------------------------------------------------------------------

    async def check(self) -> int:
        today = to_ist(datetime.now(UTC)).date().isoformat()
        added = 0
        keys = list(
            dict.fromkeys(self._watchlist_keys() + list(self._portfolio.holdings_map().keys()))
        )
        found = self._instruments.get_many(keys)
        stocks = [found[k] for k in keys if k in found and found[k].segment == "NSE_EQ"]
        added += self._research_changes(stocks)
        added += await self._moves(stocks, today)
        added += await self._plan_checks(today)
        added += self._analysis_checks()
        added += self._sources(today)
        added += self._validation()
        added += await self._market(today)
        added += await self._results(stocks)
        added += await self._portfolio_drop(today)
        self._db.execute(
            "DELETE FROM events WHERE created_at < ?",
            [datetime.now(UTC) - timedelta(days=KEEP_DAYS)],
        )
        return added

    def _research_changes(self, stocks) -> int:
        n = 0
        for inst in stocks:
            report = self._research.latest(inst.instrument_key)
            if report is None:
                continue
            ch = self._research.changes(inst.instrument_key, report)
            if ch is None:
                continue
            signal = [c for c in ch.items if c.kind == "signal"]
            if not signal:
                continue
            first = signal[0]
            fact = Fact(
                id="F1",
                text=f"{inst.symbol}: {first.text} Compared with the report from "
                f"{to_ist(ch.since):%d %b %H:%M} IST.",
                source=RESEARCH,
                basis="observed",
                as_of=ch.until,
            )
            n += self.add(
                f"research:{inst.symbol}:{report.computed_at:%Y%m%d%H%M}",
                "research",
                "medium" if first.direction == "worse" else "low",
                f"{inst.symbol}: {first.text.rstrip('.')}",
                ch.summary
                + " Research scores summarise evidence; replay tests have not shown them to "
                "predict returns.",
                [fact],
                inst.symbol,
            )
        return n

    async def _moves(self, stocks, today: str) -> int:
        if not stocks:
            return 0
        try:
            quotes = await self._quotes.get([i.instrument_key for i in stocks])
        except AppError:
            return 0
        n = 0
        for inst in stocks:
            q = quotes.get(inst.instrument_key)
            if q is None or q.change_pct is None or q.freshness == "unavailable":
                continue
            move = q.change_pct / 100
            vol = await self._daily_vol(inst)
            limit = max(MOVE_FLOOR, MOVE_SIGMA * vol) if vol else MOVE_FLOOR * 1.5
            if abs(move) < limit:
                continue
            typical = f" Its typical daily move is about {pct(vol)}." if vol else ""
            fact = Fact(
                id="F1",
                text=f"{inst.symbol} moved {pct(move, True)} today to Rs {q.ltp:,.2f}.{typical}",
                source="Upstox market quote",
                basis="observed",
                as_of=datetime.now(UTC),
            )
            n += self.add(
                f"move:{inst.symbol}:{today}",
                "market",
                "medium",
                f"{inst.symbol} {'jumped' if move > 0 else 'fell'} {pct(abs(move))} today",
                f"That is unusually large for {inst.symbol}.{typical} Check the headlines before "
                "reading anything into it; one day says little about the business.",
                [fact],
                inst.symbol,
            )
        return n

    async def _daily_vol(self, inst) -> float | None:
        with contextlib.suppress(AppError):
            a = await self._portfolio._asset(inst, divs=False)
            c = a.series.closes[-127:]
            r = [y / x - 1 for x, y in zip(c[:-1], c[1:], strict=True)]
            if len(r) > 20:
                m = sum(r) / len(r)
                return math.sqrt(sum((x - m) ** 2 for x in r) / (len(r) - 1))
        return None

    async def _plan_checks(self, today: str) -> int:
        try:
            plan = await self._portfolio.plan(self._portfolio.preferences())
        except AppError:
            return 0
        n = 0
        t = plan.trades
        if t and t.basis == "holdings":
            worst = max(
                t.lines, key=lambda x: abs(x.current_weight - x.target_weight), default=None
            )
            if worst and abs(worst.current_weight - worst.target_weight) >= DRIFT_BAND:
                moves = [
                    f"{x.action} {abs(x.delta_qty)} {x.symbol}"
                    for x in t.lines
                    if x.action != "hold"
                ]
                fact = Fact(
                    id="F1",
                    text=f"{worst.symbol} is {pct(worst.current_weight, digits=0)} of your "
                    f"holdings versus {pct(worst.target_weight, digits=0)} in the "
                    f"{plan.objective.label} plan.",
                    source=ENGINE,
                    basis="estimate",
                )
                n += self.add(
                    f"drift:{today}",
                    "portfolio",
                    "medium",
                    "Your holdings have drifted from your plan",
                    f"{worst.symbol} is {pct(worst.current_weight, digits=0)} of the portfolio "
                    f"against a {pct(worst.target_weight, digits=0)} target. Moves that would "
                    "realign it: "
                    f"{', '.join(moves) or 'none above the minimum size'}; estimated charges "
                    f"Rs {t.est_costs:,.0f}.",
                    [fact],
                )
        r = plan.risk
        if r and len(plan.assets) >= 2 and r.top_risk_share >= CONCENTRATION:
            week = to_ist(datetime.now(UTC)).strftime("%G-%V")
            fact = Fact(
                id="F1",
                text=f"{r.top_risk_symbol} carries {pct(r.top_risk_share, digits=0)} of estimated "
                "portfolio risk.",
                source=ENGINE,
                basis="estimate",
            )
            n += self.add(
                f"concentration:{r.top_risk_symbol}:{week}",
                "portfolio",
                "medium",
                f"Half your risk sits in {r.top_risk_symbol}",
                f"{r.top_risk_symbol} drives {pct(r.top_risk_share, digits=0)} of the plan's "
                "estimated swings. The Lower risk objective or a diversifying addition would "
                "spread it.",
                [fact],
                r.top_risk_symbol,
            )
        return n

    def _analysis_checks(self) -> int:
        a = self._portfolio.latest()
        if a is None or not a.candidates:
            return 0
        best = a.candidates[0]
        fact = Fact(
            id="F1",
            text=best.explanation,
            source=f"{ENGINE}, {a.candidate_universe} screen",
            basis="estimate",
            as_of=a.computed_at,
        )
        return int(
            self.add(
                f"candidate:{best.symbol}",
                "opportunity",
                "low",
                f"{best.symbol} is now the best diversifier for your stocks",
                f"Among {a.candidates_screened} {a.candidate_universe} stocks, {best.symbol} "
                f"({best.sector}) would lower estimated swings the most, from "
                f"{pct(best.vol_before)} to {pct(best.vol_after)}.",
                [fact],
                best.symbol,
            )
        )

    def _sources(self, today: str) -> int:
        n = 0
        for s in self._monitor.states():
            if s.status == "down":
                label = self._monitor.LABELS.get(s.name, s.name)
                n += self.add(
                    f"source:{s.name}:{today}",
                    "data",
                    "low",
                    f"{label} is not responding",
                    f"{s.consecutive_failures} attempts in a row failed ({s.last_error}). Features "
                    "that use it show their gaps instead of guessing.",
                    [],
                )
        return n

    def _validation(self) -> int:
        v = self._lab.latest()
        if v is None:
            return 0
        comp = next((t for t in v.tests if t.key == "composite"), None)
        detail = (
            f" The combined score's average rank correlation with the next month was "
            f"{comp.mean_ic:+.3f} over {comp.months} months."
            if comp and comp.mean_ic is not None
            else ""
        )
        fact = Fact(
            id="F1",
            text=v.headline + detail,
            source="FinCortext research validation",
            basis="measured",
            as_of=v.computed_at,
        )
        return int(
            self.add(
                f"validation:{v.computed_at:%Y%m%d}",
                "research",
                "low",
                "Research validation updated",
                v.headline + detail,
                [fact],
            )
        )

    # --- market, results and portfolio-level checks ----------------------------------------

    async def _market(self, today: str) -> int:
        """NIFTY 50 crossing its 200-day average, and India VIX jumping."""
        n = 0
        with contextlib.suppress(AppError):
            nifty = await self._portfolio._asset(
                self._instruments.by_symbol("NIFTY", "NSE_INDEX"), divs=False
            )
            c = nifty.series.closes
            if len(c) > 205:
                above_now = c[-1] > (ta.sma(c, 200) or 0)
                above_before = c[-6] > (ta.sma(c[:-5], 200) or 0)
                if above_now != above_before:
                    word = "rose above" if above_now else "fell below"
                    fact = Fact(
                        id="F1",
                        text=f"NIFTY 50 closed at {c[-1]:,.0f}, {word} its 200-day average "
                        f"({ta.sma(c, 200):,.0f}) within the last week.",
                        source="Upstox daily closes",
                        basis="observed",
                    )
                    n += self.add(
                        f"regime:nifty200:{today}",
                        "market",
                        "medium",
                        f"The NIFTY 50 {word} its 200-day average",
                        "A common gauge of the market's longer trend changed sides. It has not "
                        "reliably predicted what comes next (FinCortext's own replay found no "
                        "timing value), but falls below it have often come with bigger swings.",
                        [fact],
                        boost=5,
                    )
        with contextlib.suppress(AppError):
            vix = await self._portfolio._asset(
                self._instruments.by_symbol("INDIA VIX", "NSE_INDEX"), divs=False
            )
            v = vix.series.closes
            if len(v) > 6 and v[-6] > 0:
                jump = v[-1] / v[-6] - 1
                if v[-1] >= 18 and jump >= 0.3:
                    fact = Fact(
                        id="F1",
                        text=f"India VIX rose {pct(jump, True)} in five sessions to {v[-1]:.1f}.",
                        source="Upstox daily closes",
                        basis="observed",
                    )
                    n += self.add(
                        f"regime:vix:{today}",
                        "market",
                        "medium",
                        f"Expected market swings jumped (India VIX {v[-1]:.1f})",
                        "Option prices imply larger moves ahead. Your plan's stress replays show "
                        "how this mix behaved in past sell-offs.",
                        [fact],
                        boost=5,
                    )
        return n

    async def _results(self, stocks) -> int:
        """A newly reported quarter for a watched or held stock, compared with a year earlier."""
        n = 0
        for inst in stocks:
            try:
                rows = await self._portfolio._data.statements(inst.symbol)
            except AppError:
                continue
            q_rev = sorted((d, v) for item, d, v in rows if item == "quarterlyTotalRevenue")
            q_ni = dict((d, v) for item, d, v in rows if item == "quarterlyNetIncome")
            if len(q_rev) < 5:
                continue
            end, rev = q_rev[-1]
            year_ago = next((v for d, v in q_rev if abs((end - d).days - 365) <= 20), None)
            ni, ni0 = (
                q_ni.get(end),
                next((v for d, v in q_ni.items() if abs((end - d).days - 365) <= 20), None),
            )
            if not year_ago or year_ago <= 0:
                continue
            g_rev = rev / year_ago - 1
            parts = [f"revenue {pct(g_rev, True)}"]
            g_ni = ni / ni0 - 1 if ni is not None and ni0 and ni0 > 0 else None
            if g_ni is not None:
                parts.append(f"net income {pct(g_ni, True)}")
            weak = g_rev < 0 or (g_ni is not None and g_ni < -0.1)
            fact = Fact(
                id="F1",
                text=f"{inst.symbol} quarter ended {end:%d %b %Y}: {', '.join(parts)} year on "
                "year.",
                source="Yahoo Finance quarterly statements",
                basis="observed",
            )
            n += self.add(
                f"results:{inst.symbol}:{end:%Y%m%d}",
                "results",
                "medium" if weak else "low",
                f"{inst.symbol} results: {', '.join(parts)} on a year ago",
                f"The quarter ended {end:%d %b %Y}. The research agents will use it at their next "
                "run; check whether the change is one-off before reading much into it.",
                [fact],
                inst.symbol,
            )
        return n

    async def _portfolio_drop(self, today: str) -> int:
        """Your holdings, valued at today's quantities, down 5% or more over five sessions."""
        held = {k: q for k, (q, _) in self._portfolio.holdings_map().items() if q > 0}
        if not held:
            return 0
        now_v = then_v = 0.0
        for key, qty in held.items():
            with contextlib.suppress(AppError):
                a = await self._portfolio._asset(self._instruments.get(key), divs=False)
                c = a.series.closes
                if len(c) > 6:
                    now_v += qty * c[-1]
                    then_v += qty * c[-6]
        if then_v <= 0:
            return 0
        change = now_v / then_v - 1
        if change > -0.05:
            return 0
        fact = Fact(
            id="F1",
            text=f"Your holdings at current quantities moved {pct(change, True)} over five "
            f"sessions (Rs {then_v:,.0f} to Rs {now_v:,.0f}).",
            source="Upstox daily closes and your holdings",
            basis="observed",
        )
        return int(
            self.add(
                f"drawdown:{today}",
                "portfolio",
                "high" if change <= -0.1 else "medium",
                f"Your portfolio is {pct(abs(change))} down this week",
                "Falls like this happen; your plan's stress replays show how far this mix fell in "
                "past sell-offs. Selling after a drop locks it in, so check the reasons first.",
                [fact],
                boost=10,
            )
        )
