"""Paper trading: orders against live NSE prices with virtual cash.

Orders are matched against live quotes while the market is open: a market order fills at the
last traded price, a limit buy (sell) when the price is at or below (above) the limit, and a
stop-loss order when the price crosses its trigger, at the price seen then. Orders placed while
the market is closed wait for the next session. A fill needs a quote that traded today, so no
order fills on an exchange holiday or at a stale price.

Charges follow the NSE delivery schedule in ``tools.charges``. Sells close the oldest lots
first (FIFO, as Indian tax rules do) and each closed lot becomes a trade in the journal, with
the buy and sell reasons, the charges and the NIFTY 50 move over the same dates.
"""

import asyncio
import contextlib
import json
import logging
import math
import uuid
from datetime import UTC, date, datetime, time, timedelta

from app.db import Database, _as_utc
from app.errors import AppError, NotFound
from app.schemas.market import Instrument, Quote
from app.schemas.paper import (
    AccountActivity,
    ChargesOut,
    ClosedTrade,
    JournalEntry,
    OrderIn,
    OrderPreview,
    PaperOrder,
)
from app.services.instruments import InstrumentService
from app.services.journal import build_journal, build_scorecard
from app.services.research_data import ResearchData
from app.services.session import SessionClock
from app.services.tracker import TrackerService
from app.tools.charges import break_even, order_charges
from app.tools.market_hours import to_ist

log = logging.getLogger(__name__)

SESSION_OPEN = time(9, 15)
SESSION_CLOSE = time(15, 30)
FILL_EVERY_OPEN = 3.0  # seconds between matching passes while the market is open
FILL_EVERY_CLOSED = 60.0
MAX_OPEN_ORDERS = 50
INDEX_KEY = "NSE_INDEX|Nifty 50"

ORDER_COLUMNS = (
    "id, instrument_key, side, kind, validity, quantity, limit_price, trigger_price, status, "
    "created_at, session, fill_price, filled_at, fill_basis, charges, reason, tag, "
    "target_price, stop_price, parent_id, source, message, portfolio_id, est_price"
)


def _now() -> datetime:
    return datetime.now(UTC)


def _today() -> date:
    return to_ist(_now()).date()


def next_session(moment: datetime) -> date:
    """The trading day an order placed at ``moment`` belongs to: today until the close, then
    the next weekday. Exchange holidays are not known here; an order dated for a holiday simply
    waits, because nothing trades that day."""
    local = to_ist(moment)
    d = local.date()
    if local.weekday() < 5 and local.time() < SESSION_CLOSE:
        return d
    d += timedelta(days=1)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


def _fmt(d: datetime) -> str:
    local = to_ist(d)
    return f"{local:%H:%M} on {local.day} {local:%b}"


class PaperService:
    def __init__(
        self,
        db: Database,
        instruments: InstrumentService,
        data: ResearchData,
        tracker: TrackerService,
        clock: SessionClock,
        enqueue_research=None,
    ):
        self._db = db
        self._instruments = instruments
        self._data = data
        self._tracker = tracker
        self._clock = clock
        self._enqueue = enqueue_research
        self._lock = asyncio.Lock()

    # --- prices ----------------------------------------------------------------------------

    def open_order_keys(self) -> list[str]:
        return [
            r[0]
            for r in self._db.fetchall(
                "SELECT DISTINCT instrument_key FROM paper_orders WHERE status = 'OPEN'"
            )
        ]

    def _market_open(self) -> bool:
        return self._clock.state()[0] == "open"

    async def _quotes(self, keys: list[str]) -> dict[str, Quote]:
        found = self._instruments.get_many(keys)
        if not found:
            return {}
        try:
            return await self._data.quotes_for(list(found.values()))
        except AppError as exc:
            log.info("paper: quotes unavailable (%s)", exc.message)
            return {}

    @staticmethod
    def _tradable(q: Quote | None) -> bool:
        """A price an order may fill at: live or polled, and traded in today's session."""
        if q is None or not q.ltp or q.freshness not in ("live", "delayed"):
            return False
        if q.last_trade_time is not None and to_ist(q.last_trade_time).date() != _today():
            return False
        return True

    async def _index_level(self) -> float | None:
        q = (await self._quotes([INDEX_KEY])).get(INDEX_KEY)
        return q.ltp if q and q.ltp else None

    # --- orders ----------------------------------------------------------------------------

    def _paper_account(self, pid: str) -> tuple[float, str]:
        kind, _, cash, plan = self._tracker.account(pid)
        if kind != "paper":
            raise AppError("Orders work in paper trading accounts only.", status_code=422)
        return float(cash or 0.0), plan

    def _instrument(self, symbol: str) -> Instrument:
        inst = self._instruments.by_symbol(symbol.upper().strip())
        if inst.segment != "NSE_EQ":
            raise AppError("Only NSE equities can be traded.", status_code=422)
        return inst

    def held(self, pid: str, key: str) -> float:
        row = self._db.fetchone(
            "SELECT coalesce(sum(quantity), 0) FROM tracked_positions "
            "WHERE portfolio_id = ? AND instrument_key = ?",
            [pid, key],
        )
        return float(row[0]) if row else 0.0

    def _open_sell_qty(self, pid: str, key: str, exclude_children: bool = False) -> float:
        sql = (
            "SELECT coalesce(sum(quantity), 0) FROM paper_orders WHERE portfolio_id = ? "
            "AND instrument_key = ? AND side = 'SELL' AND status = 'OPEN'"
        )
        if exclude_children:
            sql += " AND parent_id IS NULL"
        row = self._db.fetchone(sql, [pid, key])
        return float(row[0]) if row else 0.0

    async def preview(self, pid: str, req: OrderIn) -> OrderPreview:
        cash, plan = self._paper_account(pid)
        inst = self._instrument(req.symbol)
        q = (await self._quotes([inst.instrument_key])).get(inst.instrument_key)
        last = q.ltp if q and q.ltp else None
        open_now = self._market_open()
        if req.kind == "LIMIT":
            price, basis = req.limit_price, "your limit price"
        elif req.kind == "SL":
            price, basis = req.trigger_price, "your trigger price"
        elif last:
            basis = "live price" if self._tradable(q) and open_now else "last traded price"
            price = last
        else:
            raise AppError(f"No price available for {inst.symbol} right now.", status_code=422)
        assert price is not None
        if req.quantity:
            qty = int(req.quantity)
        else:
            qty = math.floor((req.amount or 0) / (price * 1.002))
            if qty < 1:
                raise AppError(
                    f"Rs {req.amount:,.0f} does not buy one share of {inst.symbol} at "
                    f"Rs {price:,.2f} after charges.",
                    status_code=422,
                )
        value = qty * price
        charges = order_charges(req.side, value, plan)
        warnings: list[str] = []
        reserved = self._tracker.reserved_cash(pid)
        if req.side == "BUY":
            total = value + charges.total
            cash_after = cash - total
            if total > cash - reserved:
                warnings.append(
                    f"Not enough free cash: this needs Rs {total:,.0f}, you have "
                    f"Rs {cash - reserved:,.0f} after open orders."
                )
            if req.stop_price and req.stop_price >= price:
                warnings.append("The stop price should be below the buy price.")
            if req.target_price and req.target_price <= price:
                warnings.append("The target price should be above the buy price.")
            if cash > 0 and value / max(cash, 1) > 0.4:
                warnings.append(
                    f"This puts {value / cash:.0%} of your cash in one stock. Spreading money "
                    "over several stocks limits the damage one bad pick can do."
                )
        else:
            total = value - charges.total
            cash_after = cash + total
            free = self.held(pid, inst.instrument_key) - self._open_sell_qty(
                pid, inst.instrument_key, exclude_children=True
            )
            if qty > free:
                warnings.append(f"You can sell at most {max(0, free):g} shares of {inst.symbol}.")
        if charges.total and value and charges.total / value > 0.005:
            warnings.append(
                f"Charges are {charges.total / value:.2%} of this order: small orders lose a "
                "bigger share to fixed charges."
            )
        if req.kind == "MARKET":
            fills = (
                "Fills now at the live price."
                if open_now and self._tradable(q)
                else "Market is closed: fills at the first traded price after the next open "
                "(9:15 IST), which can differ from the last price shown."
            )
        elif req.kind == "LIMIT":
            fills = (
                f"Fills only if the price is at or {'below' if req.side == 'BUY' else 'above'} "
                f"Rs {req.limit_price:,.2f}"
                + (" today." if req.validity == "DAY" else ", until you cancel it.")
            )
        else:
            fills = (
                "Becomes a market order when the price "
                f"{'falls to' if req.side == 'SELL' else 'rises to'} "
                f"Rs {req.trigger_price:,.2f}"
                + (" today." if req.validity == "DAY" else ", until you cancel it.")
            )
        return OrderPreview(
            symbol=inst.symbol,
            side=req.side,
            quantity=qty,
            price=price,
            price_basis=basis,
            value=value,
            charges=ChargesOut(**charges.as_dict()),
            total=total,
            break_even=break_even(price, qty, plan) if req.side == "BUY" else None,
            cash_after=cash_after,
            market_open=open_now,
            fills=fills,
            warnings=warnings,
        )

    async def place(self, pid: str, req: OrderIn, source: str = "you") -> PaperOrder:
        async with self._lock:
            preview = await self.preview(pid, req)
            inst = self._instrument(req.symbol)
            cash, _ = self._paper_account(pid)
            open_count = self._db.fetchone(
                "SELECT count(*) FROM paper_orders WHERE portfolio_id = ? AND status = 'OPEN'",
                [pid],
            )
            if open_count and open_count[0] >= MAX_OPEN_ORDERS:
                raise AppError(f"At most {MAX_OPEN_ORDERS} open orders.", status_code=422)
            invalid = [w for w in preview.warnings if w.startswith(("The stop", "The target"))]
            if invalid:
                raise AppError(invalid[0], status_code=422)
            if req.side == "BUY":
                free = cash - self._tracker.reserved_cash(pid)
                if preview.total > free:
                    raise AppError(preview.warnings[0], status_code=422)
            else:
                free_qty = self.held(pid, inst.instrument_key) - self._open_sell_qty(
                    pid, inst.instrument_key, exclude_children=True
                )
                if preview.quantity > free_qty:
                    raise AppError(
                        f"You can sell at most {max(0, free_qty):g} shares of {inst.symbol}.",
                        status_code=422,
                    )
            now = _now()
            oid = uuid.uuid4().hex[:12]
            validity = "DAY" if req.kind == "MARKET" else req.validity
            self._db.execute(
                "INSERT INTO paper_orders (id, portfolio_id, instrument_key, side, kind, validity, "
                "quantity, limit_price, trigger_price, est_price, status, created_at, session, "
                "updated_at, reason, tag, target_price, stop_price, source) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'OPEN', ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    oid,
                    pid,
                    inst.instrument_key,
                    req.side,
                    req.kind,
                    validity,
                    preview.quantity,
                    req.limit_price if req.kind == "LIMIT" else None,
                    req.trigger_price if req.kind == "SL" else None,
                    preview.price,
                    now,
                    _today() if self._market_open() else next_session(now),
                    now,
                    (req.reason or "").strip() or None,
                    req.tag,
                    req.target_price,
                    req.stop_price,
                    source,
                ],
            )
        await self.match(keys=[inst.instrument_key])
        return self.order(pid, oid)

    def cancel(self, pid: str, oid: str) -> PaperOrder:
        row = self._db.fetchone(
            "SELECT status FROM paper_orders WHERE portfolio_id = ? AND id = ?", [pid, oid]
        )
        if row is None:
            raise NotFound("Order not found.")
        if row[0] != "OPEN":
            raise AppError("Only open orders can be cancelled.", status_code=422)
        self._set_status(oid, "CANCELLED", "Cancelled by you.")
        return self.order(pid, oid)

    def _set_status(self, oid: str, status: str, message: str | None) -> None:
        self._db.execute(
            "UPDATE paper_orders SET status = ?, message = ?, updated_at = ? WHERE id = ?",
            [status, message, _now(), oid],
        )

    # --- matching ----------------------------------------------------------------------------

    def _expire(self) -> None:
        """Day orders end with their session; exits left without shares end too."""
        now = _now()
        local = to_ist(now)
        today = local.date()
        closed_today = not self._market_open() and (
            local.time() >= SESSION_CLOSE or local.weekday() >= 5
        )
        for oid, session in self._db.fetchall(
            "SELECT id, session FROM paper_orders WHERE status = 'OPEN' AND validity = 'DAY'"
        ):
            if session < today or (session == today and closed_today):
                self._set_status(oid, "EXPIRED", "Day order ended with the session unfilled.")

    async def match(self, keys: list[str] | None = None) -> int:
        """One matching pass over open orders. Returns the number of fills."""
        async with self._lock:
            self._expire()
            if not self._market_open():
                return 0
            rows = self._db.fetchall(
                f"SELECT {ORDER_COLUMNS} FROM paper_orders WHERE status = 'OPEN' "
                "ORDER BY created_at"
            )
            if keys:
                rows = [r for r in rows if r[1] in keys]
            if not rows:
                return 0
            today = _today()
            quotes = await self._quotes(sorted({r[1] for r in rows} | {INDEX_KEY}))
            index = quotes.get(INDEX_KEY)
            index_level = index.ltp if index and index.ltp else None
            fills = 0
            for r in rows:
                oid, key, side, kind = r[0], r[1], r[2], r[3]
                limit, trigger, session = r[6], r[7], r[10]
                if session > today:
                    continue  # placed after the close for a later session
                q = quotes.get(key)
                if not self._tradable(q):
                    continue
                assert q is not None and q.ltp
                ltp = q.ltp
                if kind == "LIMIT" and not (
                    (side == "BUY" and ltp <= limit) or (side == "SELL" and ltp >= limit)
                ):
                    continue
                if kind == "SL" and not (
                    (side == "SELL" and ltp <= trigger) or (side == "BUY" and ltp >= trigger)
                ):
                    continue
                status = self._db.fetchone("SELECT status FROM paper_orders WHERE id = ?", [oid])
                if not status or status[0] != "OPEN":
                    continue  # cancelled by an earlier fill in this pass
                if kind == "LIMIT":
                    how = f"limit Rs {limit:,.2f} reached"
                elif kind == "SL":
                    how = f"stop triggered at Rs {trigger:,.2f}"
                else:
                    how = "last traded price"
                basis = f"{how}, filled at {_fmt(_now())}"
                if side == "BUY":
                    ok = self._fill_buy(r, ltp, basis, index_level)
                else:
                    ok = self._fill_sell(r, ltp, basis, index_level)
                fills += ok
            return fills

    def _fill_buy(self, r, price: float, basis: str, index_level: float | None) -> bool:
        oid, key, qty = r[0], r[1], float(r[5])
        pid = r[22]
        cash, plan = self._paper_account(pid)
        value = qty * price
        charges = order_charges("BUY", value, plan)
        # The order's own reservation is part of the reserved total; free it for this check.
        if value + charges.total > cash + 1e-6:
            self._set_status(
                oid,
                "REJECTED",
                f"Not enough cash at the fill price Rs {price:,.2f}: needed "
                f"Rs {value + charges.total:,.0f}, had Rs {cash:,.0f}.",
            )
            return False
        now = _now()
        self._db.execute(
            "UPDATE tracked_portfolios SET cash = cash - ? WHERE id = ?",
            [value + charges.total, pid],
        )
        self._db.execute(
            "INSERT INTO tracked_positions (id, portfolio_id, instrument_key, quantity, "
            "entry_price, entry_at, entry_basis, charges, reason, tag, index_at_entry, order_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                uuid.uuid4().hex[:12],
                pid,
                key,
                qty,
                price,
                now,
                f"paper buy, {basis}",
                charges.total,
                r[15],
                r[16],
                index_level,
                oid,
            ],
        )
        self._db.execute(
            "UPDATE paper_orders SET status = 'FILLED', fill_price = ?, filled_at = ?, "
            "fill_basis = ?, charges = ?, updated_at = ? WHERE id = ?",
            [price, now, basis, json.dumps(charges.as_dict()), now, oid],
        )
        target, stop, source = r[17], r[18], r[20]
        when = f"{to_ist(now).day} {to_ist(now):%b}"
        for exit_kind, level, text in (
            ("LIMIT", target, f"Target from your buy on {when}"),
            ("SL", stop, f"Stop-loss from your buy on {when}"),
        ):
            if level:
                self._db.execute(
                    "INSERT INTO paper_orders (id, portfolio_id, instrument_key, side, kind, "
                    "validity, quantity, limit_price, trigger_price, status, created_at, session, "
                    "updated_at, reason, tag, parent_id, source) VALUES "
                    "(?, ?, ?, 'SELL', ?, 'GTC', ?, ?, ?, 'OPEN', ?, ?, ?, ?, ?, ?, ?)",
                    [
                        uuid.uuid4().hex[:12],
                        pid,
                        key,
                        exit_kind,
                        qty,
                        level if exit_kind == "LIMIT" else None,
                        level if exit_kind == "SL" else None,
                        now,
                        _today(),
                        now,
                        text,
                        r[16],
                        oid,
                        source,
                    ],
                )
        if self._enqueue:
            with contextlib.suppress(Exception):
                self._enqueue(key)
        return True

    def _fill_sell(self, r, price: float, basis: str, index_level: float | None) -> bool:
        oid, key, qty, pid = r[0], r[1], float(r[5]), r[22]
        _, plan = self._paper_account(pid)
        lots = self._db.fetchall(
            "SELECT id, quantity, entry_price, entry_at, coalesce(charges, 0), reason, tag, "
            "index_at_entry FROM tracked_positions WHERE portfolio_id = ? AND instrument_key = ? "
            "ORDER BY entry_at, id",
            [pid, key],
        )
        held = sum(float(lot[1]) for lot in lots)
        if held + 1e-9 < qty:
            self._set_status(
                oid, "REJECTED", f"You hold {held:g} shares; this order was for {qty:g}."
            )
            return False
        now = _now()
        value = qty * price
        charges = order_charges("SELL", value, plan)
        self._db.execute(
            "UPDATE tracked_portfolios SET cash = cash + ? WHERE id = ?",
            [value - charges.total, pid],
        )
        left = qty
        for lot_id, lot_qty, entry, entry_at, lot_charges, reason, tag, index_entry in lots:
            if left <= 1e-9:
                break
            lot_qty = float(lot_qty)
            take = min(left, lot_qty)
            share = take / lot_qty
            self._db.execute(
                "INSERT INTO paper_trades VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    uuid.uuid4().hex[:12],
                    pid,
                    key,
                    take,
                    entry,
                    entry_at,
                    float(lot_charges) * share,
                    price,
                    now,
                    charges.total * take / qty,
                    reason,
                    tag,
                    r[15],
                    index_entry,
                    index_level,
                    r[20],
                ],
            )
            if take >= lot_qty - 1e-9:
                self._db.execute("DELETE FROM tracked_positions WHERE id = ?", [lot_id])
            else:
                self._db.execute(
                    "UPDATE tracked_positions SET quantity = quantity - ?, charges = charges * ? "
                    "WHERE id = ?",
                    [take, 1 - share, lot_id],
                )
            left -= take
        self._db.execute(
            "UPDATE paper_orders SET status = 'FILLED', fill_price = ?, filled_at = ?, "
            "fill_basis = ?, charges = ?, updated_at = ? WHERE id = ?",
            [price, now, basis, json.dumps(charges.as_dict()), now, oid],
        )
        if r[19]:  # an exit filled: its sibling (target or stop) is no longer needed
            for (sib,) in self._db.fetchall(
                "SELECT id FROM paper_orders WHERE parent_id = ? AND id <> ? AND status = 'OPEN'",
                [r[19], oid],
            ):
                self._set_status(sib, "CANCELLED", "The other exit for this buy filled first.")
        self._trim_exits(pid, key)
        return True

    def _trim_exits(self, pid: str, key: str) -> None:
        """Cancel attached target/stop pairs, newest first, while together they would sell
        more shares than are still held."""
        held = self.held(pid, key)
        rows = self._db.fetchall(
            "SELECT parent_id, max(quantity), max(created_at) AS newest FROM paper_orders "
            "WHERE portfolio_id = ? AND instrument_key = ? AND side = 'SELL' AND status = 'OPEN' "
            "AND parent_id IS NOT NULL GROUP BY parent_id ORDER BY newest DESC",
            [pid, key],
        )
        need = sum(float(q) for _, q, _ in rows)
        for parent, q, _ in rows:
            if need <= held + 1e-9:
                break
            for (oid,) in self._db.fetchall(
                "SELECT id FROM paper_orders WHERE parent_id = ? AND status = 'OPEN'", [parent]
            ):
                self._set_status(oid, "CANCELLED", "Shares already sold: exit no longer needed.")
            need -= float(q)

    # --- reading ------------------------------------------------------------------------------

    def _order_model(self, r, symbols: dict[str, str]) -> PaperOrder:
        charges = json.loads(r[14]) if r[14] else None
        return PaperOrder(
            id=r[0],
            symbol=symbols.get(r[1], r[1]),
            instrument_key=r[1],
            side=r[2],
            kind=r[3],
            validity=r[4],
            quantity=float(r[5]),
            limit_price=r[6],
            trigger_price=r[7],
            status=r[8],
            created_at=_as_utc(r[9]),
            session=r[10],
            fill_price=r[11],
            filled_at=_as_utc(r[12]) if r[12] else None,
            fill_basis=r[13],
            charges=ChargesOut(**charges) if charges else None,
            reason=r[15],
            tag=r[16],
            target_price=r[17],
            stop_price=r[18],
            parent_id=r[19],
            source=r[20],
            message=r[21],
        )

    def _symbols(self, keys) -> dict[str, str]:
        return {k: i.symbol for k, i in self._instruments.get_many(sorted(set(keys))).items()}

    def order(self, pid: str, oid: str) -> PaperOrder:
        r = self._db.fetchone(
            f"SELECT {ORDER_COLUMNS} FROM paper_orders WHERE portfolio_id = ? AND id = ?",
            [pid, oid],
        )
        if r is None:
            raise NotFound("Order not found.")
        return self._order_model(r, self._symbols([r[1]]))

    def orders(self, pid: str, limit: int = 200) -> list[PaperOrder]:
        rows = self._db.fetchall(
            f"SELECT {ORDER_COLUMNS} FROM paper_orders WHERE portfolio_id = ? "
            "ORDER BY created_at DESC LIMIT ?",
            [pid, limit],
        )
        symbols = self._symbols([r[1] for r in rows])
        return [self._order_model(r, symbols) for r in rows]

    def trades(self, pid: str) -> list[ClosedTrade]:
        rows = self._db.fetchall(
            "SELECT id, instrument_key, quantity, buy_price, buy_at, buy_charges, sell_price, "
            "sell_at, sell_charges, buy_reason, buy_tag, sell_reason, index_at_buy, "
            "index_at_sell, source FROM paper_trades WHERE portfolio_id = ? ORDER BY sell_at DESC",
            [pid],
        )
        symbols = self._symbols([r[1] for r in rows])
        out = []
        for r in rows:
            (tid, key, q, bp, bat, bch, sp, sat, sch, breason, btag, sreason, ib, isell, src) = r
            q, bp, sp = float(q), float(bp), float(sp)
            charges = float(bch) + float(sch)
            gross = (sp - bp) * q
            net = gross - charges
            bat, sat = _as_utc(bat), _as_utc(sat)
            days = (to_ist(sat).date() - to_ist(bat).date()).days
            index_return = isell / ib - 1 if ib and isell else None
            ret = net / (bp * q + float(bch))
            out.append(
                ClosedTrade(
                    id=tid,
                    symbol=symbols.get(key, key),
                    quantity=q,
                    buy_price=bp,
                    buy_at=bat,
                    sell_price=sp,
                    sell_at=sat,
                    charges=charges,
                    gross=gross,
                    net=net,
                    return_pct=ret,
                    holding_days=days,
                    term="long" if days > 365 else "short",
                    buy_reason=breason,
                    buy_tag=btag,
                    sell_reason=sreason,
                    index_return=index_return,
                    beat_index=ret > index_return if index_return is not None else None,
                    source=src,
                )
            )
        return out

    async def activity(self, pid: str) -> AccountActivity:
        self._paper_account(pid)
        portfolio = await self._tracker.portfolio(pid)
        trades = self.trades(pid)
        index_now = await self._index_level()
        lots = {
            r[0]: r[1:]
            for r in self._db.fetchall(
                "SELECT id, index_at_entry, order_id FROM tracked_positions WHERE portfolio_id = ?",
                [pid],
            )
        }
        sources = {
            r[0]: r[1]
            for r in self._db.fetchall(
                "SELECT id, source FROM paper_orders WHERE portfolio_id = ?", [pid]
            )
        }
        journal: list[JournalEntry] = build_journal(portfolio, trades, lots, sources, index_now)
        scorecard = build_scorecard(portfolio, trades, journal)
        return AccountActivity(
            orders=self.orders(pid), trades=trades, journal=journal, scorecard=scorecard
        )

    # --- background --------------------------------------------------------------------------

    async def run(self) -> None:
        while True:
            try:
                await self.match()
            except Exception:  # keep matching after an unexpected error
                log.exception("paper order matching failed")
            await asyncio.sleep(FILL_EVERY_OPEN if self._market_open() else FILL_EVERY_CLOSED)
