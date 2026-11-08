"""Strategy Lab: test simple trading rules on past prices, then run them forward on paper.

A backtest runs each stock separately with the same starting capital, trading whole shares
with full NSE delivery charges. The period is split into its earlier 70% and later 30% so the
result can be checked on years the rules were not tuned on. Forward runs evaluate the rules
after each session's close and place paper orders that fill at the next open, exactly as the
backtest assumes.
"""

import asyncio
import contextlib
import json
import logging
import uuid
from datetime import UTC, date, datetime, time, timedelta

from app.db import Database, _as_utc
from app.errors import AppError, NotFound
from app.schemas.paper import OrderIn
from app.schemas.portfolio import CurvePoint
from app.schemas.strategy import (
    BacktestIn,
    BacktestResult,
    BacktestTrade,
    ForwardIn,
    Rules,
    Segment,
    Strategy,
    StrategyIn,
    SymbolResult,
)
from app.services.candles import CandleService
from app.services.instruments import InstrumentService
from app.services.paper import PaperService
from app.services.session import SessionClock
from app.services.tracker import TrackerService
from app.tools import rules as R
from app.tools.backtest import session_date
from app.tools.market_hours import to_ist

log = logging.getLogger(__name__)

INDEX_KEY = "NSE_INDEX|Nifty 50"
WARMUP = 260  # sessions of history before the test period, for averages and the 52-week high
SPLIT = 0.7
RUN_AFTER = time(15, 45)  # forward runs use the completed session
CHECK_EVERY = 300.0
MAX_STRATEGIES = 30


def _epoch(d: date) -> int:
    return (d - date(1970, 1, 1)).days * 86400


def _pct(v: float) -> str:
    return f"{v * 100:+.1f}%"


class StrategyService:
    def __init__(
        self,
        db: Database,
        instruments: InstrumentService,
        candles: CandleService,
        paper: PaperService,
        tracker: TrackerService,
        clock: SessionClock,
    ):
        self._db = db
        self._instruments = instruments
        self._candles = candles
        self._paper = paper
        self._tracker = tracker
        self._clock = clock

    # --- data ----------------------------------------------------------------------------

    async def _bars(self, key: str, include_today: bool = False) -> list[R.Bar]:
        if include_today:
            series = await self._candles.series(key, "1D")
            candles = series.candles
        else:
            candles, _ = await self._candles.long_daily(key)
        bars = [
            R.Bar(session_date(c.time // 86400), c.open, c.high, c.low, c.close)
            for c in candles
            if c.open > 0 and c.close > 0
        ]
        return sorted({b.day: b for b in bars}.values(), key=lambda b: b.day)

    # --- backtest --------------------------------------------------------------------------

    async def backtest(self, req: BacktestIn) -> BacktestResult:
        skipped: list[str] = []
        index_bars: list[R.Bar] = []
        with contextlib.suppress(AppError):
            index_bars = await self._bars(INDEX_KEY)
        index_close = {b.day: b.close for b in index_bars}
        results: list[SymbolResult] = []
        for symbol in dict.fromkeys(s.upper().strip() for s in req.symbols):
            try:
                inst = self._instruments.by_symbol(symbol)
                bars = await self._bars(inst.instrument_key)
            except AppError as exc:
                skipped.append(f"{symbol}: {exc.message}")
                continue
            start_day = bars[-1].day - timedelta(days=round(365.25 * req.years)) if bars else None
            start_i = next((i for i, b in enumerate(bars) if b.day >= start_day), None)
            if start_i is None or start_i < 60 or len(bars) - start_i < 60:
                skipped.append(
                    f"{symbol}: not enough price history for a {req.years}-year test "
                    "(needs a year of warm-up before it)."
                )
                continue
            results.append(
                await asyncio.to_thread(self._one, symbol, bars, start_i, req, index_close)
            )
        rules_text = R.describe_rules(req.rules)
        return BacktestResult(
            rules_text=rules_text,
            results=results,
            skipped=skipped,
            summary=self._summary(results),
            assumptions=[
                "Signals use each session's close; orders fill at the next session's open.",
                "Stops and targets fill at their level, or at the open if the price gapped "
                "past it. If one day touches both, the stop is assumed to come first.",
                "Whole shares only, all available cash per trade, NSE delivery charges on "
                "every order. Prices are adjusted for splits and bonuses; dividends are left "
                "out of both the strategy and buy-and-hold.",
                "Past results do not predict future ones. A handful of trades is a small "
                "sample: treat it as a first test of an idea, not proof.",
            ],
            computed_at=datetime.now(UTC),
        )

    def _one(self, symbol, bars, start_i, req: BacktestIn, index_close) -> SymbolResult:
        run = R.run_rules(bars, req.rules, start_i, req.capital, req.plan)
        hold = R.hold_curve(bars, start_i, req.capital, req.plan)
        period = bars[start_i:]
        days = [b.day for b in period]
        final = run.equity[-1]
        total = final / req.capital - 1
        years = max((days[-1] - days[0]).days / 365.25, 1 / 365.25)
        cagr = (final / req.capital) ** (1 / years) - 1 if final > 0 and years >= 1 else None
        closed = [t for t in run.trades if t.exit_reason != "still held"]
        trades = [
            BacktestTrade(
                entry_date=bars[t.entry_i].day,
                entry_price=t.entry_price,
                exit_date=bars[t.exit_i or t.entry_i].day,
                exit_price=t.exit_price or t.entry_price,
                exit_reason=t.exit_reason or "",
                quantity=t.quantity,
                net=t.net,
                return_pct=t.net / (t.entry_price * t.quantity + t.buy_charges),
                days=(t.exit_i or t.entry_i) - t.entry_i,
            )
            for t in run.trades
        ]
        closed_models = [x for x in trades if x.exit_reason != "still held"]
        wins = [x for x in closed_models if x.net > 0]
        losses = [x for x in closed_models if x.net <= 0]
        # index over the same dates
        idx = [index_close.get(d) for d in days]
        known = [(d, v) for d, v in zip(days, idx, strict=True) if v]
        index_curve = (
            [CurvePoint(time=_epoch(d), value=v / known[0][1]) for d, v in known] if known else []
        )
        index_return = known[-1][1] / known[0][1] - 1 if len(known) > 1 else None
        hold_return = hold[-1] / req.capital - 1
        cut = int(len(period) * SPLIT)
        segments = []
        for label, a, b in (("Earlier 70%", 0, cut), ("Later 30%", cut, len(period) - 1)):
            if b <= a:
                continue
            base_eq = run.equity[a - 1] if a > 0 else req.capital
            base_hold = hold[a - 1] if a > 0 else req.capital
            segments.append(
                Segment(
                    label=label,
                    start=days[a],
                    end=days[b],
                    strategy_return=run.equity[b] / base_eq - 1,
                    hold_return=hold[b] / base_hold - 1,
                    trades=sum(1 for t in run.trades if start_i + a <= t.entry_i <= start_i + b),
                )
            )
        verdict = self._verdict(total, hold_return, index_return, len(closed), segments)
        step = max(1, len(period) // 600)  # keep charts light: about 600 points
        keep = sorted(set(range(0, len(period), step)) | {len(period) - 1})
        return SymbolResult(
            symbol=symbol,
            start=days[0],
            end=days[-1],
            final_value=final,
            total_return=total,
            cagr=cagr,
            max_drawdown=R.max_drawdown(run.equity),
            trades=trades,
            win_rate=len(wins) / len(closed_models) if closed_models else None,
            average_win=sum(x.return_pct for x in wins) / len(wins) if wins else None,
            average_loss=sum(x.return_pct for x in losses) / len(losses) if losses else None,
            exposure=run.held_days / len(period),
            charges=run.charges,
            hold_return=hold_return,
            index_return=index_return,
            equity=[
                CurvePoint(time=_epoch(days[i]), value=run.equity[i] / req.capital) for i in keep
            ],
            hold=[CurvePoint(time=_epoch(days[i]), value=hold[i] / req.capital) for i in keep],
            index=[
                index_curve[i]
                for i in sorted(set(range(0, len(index_curve), step)) | {len(index_curve) - 1})
            ]
            if index_curve
            else [],
            segments=segments,
            verdict=verdict,
            open_trade=bool(run.trades) and run.trades[-1].exit_reason == "still held",
        )

    @staticmethod
    def _verdict(total, hold, index, closed, segments) -> str:
        if closed == 0:
            return "The rules never completed a trade in this period, so there is nothing to judge."
        parts = [f"{closed} closed trade{'s' if closed != 1 else ''}, {_pct(total)} in total"]
        parts.append(f"{'beating' if total > hold else 'trailing'} buy-and-hold ({_pct(hold)})")
        if index is not None:
            parts.append(f"the NIFTY 50 did {_pct(index)}")
        text = ", ".join(parts) + "."
        if len(segments) == 2:
            early, late = segments
            early_edge = early.strategy_return - early.hold_return
            late_edge = late.strategy_return - late.hold_return
            edge = 0.01  # under a percentage point is "about the same"
            if early_edge > edge and late_edge < -edge:
                text += (
                    " It beat holding in the earlier years but not in the later ones: the rules "
                    "may fit the past better than they predict."
                )
            elif early_edge > edge and late_edge > edge:
                text += " It beat holding in both the earlier and later parts of the period."
            elif early_edge < -edge and late_edge > edge:
                text += " It trailed holding early on but did better in the later years."
        if closed < 5:
            text += " Fewer than 5 trades: too few to tell skill from luck."
        return text

    @staticmethod
    def _summary(results: list[SymbolResult]) -> str:
        if not results:
            return "No stock could be tested."
        beat = sum(r.total_return > r.hold_return for r in results)
        trades = sum(len([t for t in r.trades if t.exit_reason != "still held"]) for r in results)
        avg = sum(r.total_return for r in results) / len(results)
        hold = sum(r.hold_return for r in results) / len(results)
        text = (
            f"Tested on {len(results)} stock{'s' if len(results) != 1 else ''}: the rules beat "
            f"buy-and-hold on {beat}, with {trades} closed trades in all. Average result "
            f"{_pct(avg)} against {_pct(hold)} for holding."
        )
        indexed = [r for r in results if r.index_return is not None]
        if indexed:
            ahead = sum(r.total_return > r.index_return for r in indexed)
            text += (
                f" Against simply holding the NIFTY 50 over the same dates "
                f"({_pct(indexed[0].index_return)}), the rules came out ahead on {ahead} of "
                f"{len(indexed)}."
            )
        return text

    # --- saved strategies --------------------------------------------------------------------

    def _model(self, r) -> Strategy:
        sid, name, rules, created, pid, symbols, per_trade, active, last_run, note = r
        parsed = Rules.model_validate_json(rules) if isinstance(rules, str) else Rules(**rules)
        pname = None
        if pid:
            row = self._db.fetchone("SELECT name FROM tracked_portfolios WHERE id = ?", [pid])
            pname = row[0] if row else None
        return Strategy(
            id=sid,
            name=name,
            rules=parsed,
            rules_text=R.describe_rules(parsed),
            symbols=json.loads(symbols) if isinstance(symbols, str) else (symbols or []),
            created_at=_as_utc(created),
            portfolio_id=pid,
            portfolio_name=pname,
            per_trade=per_trade,
            active=bool(active),
            last_run=last_run,
            last_note=note,
        )

    _COLS = (
        "id, name, rules, created_at, portfolio_id, symbols, per_trade, active, last_run, last_note"
    )

    def all(self) -> list[Strategy]:
        rows = self._db.fetchall(f"SELECT {self._COLS} FROM strategies ORDER BY created_at DESC")
        return [self._model(r) for r in rows]

    def get(self, sid: str) -> Strategy:
        r = self._db.fetchone(f"SELECT {self._COLS} FROM strategies WHERE id = ?", [sid])
        if r is None:
            raise NotFound("Strategy not found.")
        return self._model(r)

    def save(self, req: StrategyIn) -> Strategy:
        count = self._db.fetchone("SELECT count(*) FROM strategies")
        if count and count[0] >= MAX_STRATEGIES:
            raise AppError(f"At most {MAX_STRATEGIES} saved strategies.", status_code=422)
        symbols = []
        for s in dict.fromkeys(x.upper().strip() for x in req.symbols):
            inst = self._instruments.by_symbol(s)
            if inst.segment != "NSE_EQ":
                raise AppError(f"{s} is not an NSE equity.", status_code=422)
            symbols.append(inst.symbol)
        sid = uuid.uuid4().hex[:12]
        self._db.execute(
            "INSERT INTO strategies (id, name, rules, created_at, symbols, active) "
            "VALUES (?, ?, ?, ?, ?, FALSE)",
            [
                sid,
                req.name.strip(),
                req.rules.model_dump_json(),
                datetime.now(UTC),
                json.dumps(symbols),
            ],
        )
        return self.get(sid)

    def delete(self, sid: str) -> None:
        self.get(sid)
        self._db.execute("DELETE FROM strategies WHERE id = ?", [sid])

    def start(self, sid: str, req: ForwardIn) -> Strategy:
        self.get(sid)
        kind, _, cash, _ = self._tracker.account(req.portfolio_id)
        if kind != "paper":
            raise AppError("Strategies trade in paper trading accounts only.", status_code=422)
        self._db.execute(
            "UPDATE strategies SET portfolio_id = ?, per_trade = ?, active = TRUE, "
            "last_note = ? WHERE id = ?",
            [
                req.portfolio_id,
                req.per_trade,
                "Started: rules are checked after each session's close.",
                sid,
            ],
        )
        return self.get(sid)

    def stop(self, sid: str) -> Strategy:
        self.get(sid)
        self._db.execute(
            "UPDATE strategies SET active = FALSE, last_note = ? WHERE id = ?",
            ["Stopped. Open positions stay in the account until you sell them.", sid],
        )
        return self.get(sid)

    # --- forward runs -----------------------------------------------------------------------

    def _strategy_lots(self, pid: str, key: str, sid: str) -> list[tuple]:
        return self._db.fetchall(
            "SELECT p.quantity, p.entry_at FROM tracked_positions p JOIN paper_orders o "
            "ON o.id = p.order_id WHERE p.portfolio_id = ? AND p.instrument_key = ? "
            "AND o.source = ?",
            [pid, key, f"strategy:{sid}"],
        )

    def _pending(self, pid: str, key: str, sid: str, side: str) -> bool:
        row = self._db.fetchone(
            "SELECT count(*) FROM paper_orders WHERE portfolio_id = ? AND instrument_key = ? "
            "AND source = ? AND side = ? AND status = 'OPEN' AND parent_id IS NULL",
            [pid, key, f"strategy:{sid}", side],
        )
        return bool(row and row[0])

    async def run_once(self, sid: str, today: date) -> str:
        s = self.get(sid)
        if not s.active or not s.portfolio_id or not s.per_trade:
            return "Not active."
        notes: list[str] = []
        for symbol in s.symbols:
            try:
                inst = self._instruments.by_symbol(symbol)
                bars = await self._bars(inst.instrument_key, include_today=True)
            except AppError as exc:
                notes.append(f"{symbol}: no prices ({exc.message})")
                continue
            if not bars or bars[-1].day != today:
                notes.append(f"{symbol}: no session today")
                continue
            sig = R.Signals(bars)
            i = len(bars) - 1
            key = inst.instrument_key
            lots = self._strategy_lots(s.portfolio_id, key, sid)
            held = sum(float(q) for q, _ in lots)
            try:
                if held > 0 and not self._pending(s.portfolio_id, key, sid, "SELL"):
                    first = min(_as_utc(at) for _, at in lots)
                    sessions = sum(1 for b in bars if b.day > to_ist(first).date())
                    reason = None
                    if s.rules.exit and sig.any(s.rules.exit, i):
                        hit = next(c for c in s.rules.exit if sig.holds(c, i))
                        reason = f"Strategy '{s.name}' exit: {R.describe(hit)}"
                    elif s.rules.max_days and sessions >= s.rules.max_days:
                        reason = f"Strategy '{s.name}' exit: held {s.rules.max_days} days"
                    if reason:
                        await self._paper.place(
                            s.portfolio_id,
                            OrderIn(symbol=symbol, side="SELL", quantity=int(held), reason=reason),
                            source=f"strategy:{sid}",
                        )
                        notes.append(f"{symbol}: sell order placed")
                elif held == 0 and not self._pending(s.portfolio_id, key, sid, "BUY"):
                    if sig.all(s.rules.entry, i):
                        close = bars[-1].close
                        await self._paper.place(
                            s.portfolio_id,
                            OrderIn(
                                symbol=symbol,
                                side="BUY",
                                amount=s.per_trade,
                                reason=f"Strategy '{s.name}': "
                                + " and ".join(R.describe(c) for c in s.rules.entry),
                                tag="Strategy",
                                stop_price=round(close * (1 - s.rules.stop_loss), 2)
                                if s.rules.stop_loss
                                else None,
                                target_price=round(close * (1 + s.rules.take_profit), 2)
                                if s.rules.take_profit
                                else None,
                            ),
                            source=f"strategy:{sid}",
                        )
                        notes.append(f"{symbol}: buy order placed for the next open")
            except AppError as exc:
                notes.append(f"{symbol}: order not placed ({exc.message})")
        note = (f"Checked {today:%d %b}: " + ("; ".join(notes) if notes else "no signals."))[:500]
        self._db.execute(
            "UPDATE strategies SET last_run = ?, last_note = ? WHERE id = ?", [today, note, sid]
        )
        return note

    async def run(self) -> None:
        while True:
            try:
                local = to_ist(datetime.now(UTC))
                if (
                    local.weekday() < 5
                    and local.time() >= RUN_AFTER
                    and self._clock.state()[0] != "open"
                ):
                    today = local.date()
                    for (sid,) in self._db.fetchall(
                        "SELECT id FROM strategies WHERE active AND (last_run IS NULL OR "
                        "last_run < ?)",
                        [today],
                    ):
                        await self.run_once(sid, today)
            except Exception:
                log.exception("strategy forward run failed")
            await asyncio.sleep(CHECK_EVERY)
