"""Research validation: replay the agents on past dates with only the data available then, and
measure whether their scores lined up with what happened next.

On each month's first session the replay rebuilds a research context from information dated
on or before that session: the last 260 daily closes of the stock, its peers, its sector
index, the NIFTY 50 and India VIX; FRED macro observations old enough to have been published
(two days for daily series, sixty for monthly ones); and annual statement ratios 75 days after
the fiscal year ended. The unchanged Firm, Industry and Macro agents score that context. The
score is compared with the stock's return from the next session over the following 21
sessions, so no score ever sees the returns it is judged on.

What cannot be replayed is listed, not guessed: historical headlines and analyst ratings
(Sentiment), and valuation multiples (per-share history is not adjusted for bonuses and some
companies report in another currency). Those components are judged only by forward tracking
of the reports the app stores from now on.
"""

import asyncio
import bisect
import contextlib
import json
import logging
import time
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from datetime import UTC, date, datetime, timedelta

from app.agents import firm, industry, macro
from app.agents.base import Peer, PriceSeries, ResearchContext
from app.db import Database, _as_utc
from app.errors import AppError, NotFound
from app.providers.yahoo import Fundamentals
from app.schemas.market import Instrument
from app.schemas.research import ResearchReport
from app.schemas.validation import (
    ForwardSignal,
    ForwardTracking,
    SignalTest,
    SignalValidation,
    Untestable,
    ValidationStatus,
    YearIC,
)
from app.services.instruments import InstrumentService
from app.services.research import composite
from app.services.research_data import MACRO_SERIES, SECTOR_INDEX, ResearchData, macro_indicator
from app.tools import evaluation as E
from app.tools.backtest import session_date
from app.tools.market_hours import to_ist
from app.tools.portfolio import suspicious_jump

log = logging.getLogger(__name__)

UNIVERSE = "NIFTY 500"  # broader than the large caps: weaker winner bias
HORIZON = 21
WINDOW = 260  # the agents look back at most 252 sessions
MIN_HISTORY = 253
MAX_PEERS = 12
STATEMENT_LAG = timedelta(days=75)
SERIES_LAG = {"in10y": timedelta(days=60), "incpi": timedelta(days=60)}
DAILY_LAG = timedelta(days=2)
REFRESH_AFTER = timedelta(days=7)
TRACK_MIN_PAIRS = 30
TRACK_MIN_MONTHS = 6
OUTCOME_CAP = (-0.6, 1.0)  # one-month outcomes beyond this are data errors or one-offs

FIRM_INPUTS = "Price technicals; profitability, growth and leverage from annual statements"
AGENTS = {
    "firm": ("Company (Firm agent)", FIRM_INPUTS),
    "industry": ("Industry agent", "Sector index, NIFTY 50 and in-universe peer prices"),
    "macro": ("Macro agent", "FRED series as published then; NIFTY 50 trend; India VIX"),
}
UNTESTABLE = [
    Untestable(
        agent="sentiment",
        component="News tone",
        reason="No free archive of past headlines; judged by forward tracking only.",
    ),
    Untestable(
        agent="sentiment",
        component="Analyst consensus and target gap",
        reason="No free history of analyst ratings or price targets.",
    ),
    Untestable(
        agent="firm",
        component="Valuation (P/E, price/book)",
        reason="Per-share history is not adjusted for bonuses and some companies report in "
        "another currency, so past multiples would be wrong.",
    ),
]


def pit_fundamentals(symbol: str, rows: list[tuple[str, date, float]], on: date):
    """Statement ratios as they could be known on ``on`` (75 days after fiscal year end)."""
    known: dict[str, list[tuple[date, float]]] = defaultdict(list)
    for item, end, value in rows:
        if end + STATEMENT_LAG <= on:
            known[item].append((end, value))
    income = sorted(known.get("annualNetIncome", []))
    if not income:
        return None
    end = income[-1][0]

    def at(item: str, period: date) -> float | None:
        return next((v for e, v in known.get(item, []) if e == period), None)

    prev = income[-2][0] if len(income) >= 2 else None
    ni, rev, op = (
        at("annualNetIncome", end),
        at("annualTotalRevenue", end),
        at("annualOperatingIncome", end),
    )
    eq, debt = at("annualStockholdersEquity", end), at("annualTotalDebt", end)
    f = Fundamentals(symbol=symbol, fetched_at=datetime(on.year, on.month, on.day, tzinfo=UTC))
    f.roe = ni / eq if ni is not None and eq and eq > 0 else None
    f.profit_margin = ni / rev if ni is not None and rev and rev > 0 else None
    f.operating_margin = op / rev if op is not None and rev and rev > 0 else None
    f.debt_to_equity = debt / eq if debt is not None and eq and eq > 0 else None
    if prev is not None:
        rev0, ni0 = at("annualTotalRevenue", prev), at("annualNetIncome", prev)
        f.revenue_growth = rev / rev0 - 1 if rev is not None and rev0 and rev0 > 0 else None
        f.earnings_growth = ni / ni0 - 1 if ni is not None and ni0 and ni0 > 0 else None
    return f


class _Series:
    def __init__(self, label: str, pairs: list[tuple[int, float]], source: str):
        self.label = label
        self.days = [t // 86400 for t, _ in pairs]
        self.times = [t for t, _ in pairs]
        self.closes = [c for _, c in pairs]
        self.source = source

    def upto(self, day: int, as_of: datetime) -> PriceSeries | None:
        i = bisect.bisect_right(self.days, day)
        if i == 0:
            return None
        a = max(0, i - WINDOW)
        return PriceSeries(self.label, self.times[a:i], self.closes[a:i], self.source, as_of)

    def close_on(self, day: int) -> float | None:
        i = bisect.bisect_left(self.days, day)
        return self.closes[i] if i < len(self.days) and self.days[i] == day else None

    def count_upto(self, day: int) -> int:
        return bisect.bisect_right(self.days, day)


class SignalLab:
    def __init__(self, db: Database, instruments: InstrumentService, data: ResearchData):
        self._db = db
        self._instruments = instruments
        self._data = data
        self._state: tuple[str, str | None] = ("not_started", None)
        self._progress: str | None = None
        self._task: asyncio.Task | None = None

    # --- job control -----------------------------------------------------------------

    def latest(self) -> SignalValidation | None:
        row = self._db.fetchone("SELECT payload FROM lab_runs WHERE id = 'latest'")
        if not row:
            return None
        try:
            return SignalValidation.model_validate(json.loads(row[0]))
        except ValueError:
            return None

    def _stale(self) -> bool:
        row = self._db.fetchone("SELECT computed_at FROM lab_runs WHERE id = 'latest'")
        return row is None or datetime.now(UTC) - _as_utc(row[0]) > REFRESH_AFTER

    def request_run(self, force: bool = False) -> None:
        if self._task is not None and not self._task.done():
            return
        if not force and not self._stale():
            return
        self._state = ("queued", None)
        self._task = asyncio.create_task(self._job())

    async def _job(self) -> None:
        self._state = ("running", None)
        try:
            await self._instruments.ready.wait()
            result = await self.run()
            self._db.execute(
                "INSERT OR REPLACE INTO lab_runs VALUES ('latest', ?, ?)",
                [result.model_dump_json(), result.computed_at],
            )
            self._state = ("ready", None)
        except AppError as exc:
            self._state = ("failed", exc.message)
        except Exception:
            log.exception("signal validation failed")
            self._state = ("failed", "Research validation failed unexpectedly.")
        finally:
            self._progress = None

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    def status(self) -> ValidationStatus:
        result = self.latest()
        state, error = self._state
        if state == "not_started" and result is not None:
            state = "ready"
        return ValidationStatus(state=state, error=error, progress=self._progress, result=result)  # type: ignore[arg-type]

    def verdicts(self) -> dict[str, str]:
        """Agent key (and "composite") -> verdict of the latest validation run."""
        r = self.latest()
        return {t.key: t.verdict for t in r.tests if t.kind != "factor"} if r else {}

    # --- data ------------------------------------------------------------------------

    async def _series(self, inst: Instrument) -> _Series | None:
        try:
            s = await self._data.long_daily(inst)
        except AppError:
            return None
        return _Series(inst.symbol, s.pairs, s.source)

    def _index(self, symbol: str) -> Instrument | None:
        try:
            return self._instruments.by_symbol(symbol, "NSE_INDEX")
        except NotFound:
            return None

    # --- run -------------------------------------------------------------------------

    async def run(self) -> SignalValidation:
        started = time.perf_counter()
        members = self._instruments.constituents(UNIVERSE)
        if not members:
            raise AppError(f"{UNIVERSE} constituents are not loaded yet.")
        self._progress = f"Loading ten years of prices for {len(members)} stocks"
        slots = asyncio.Semaphore(8)

        async def one(i: Instrument):
            async with slots:
                return await self._series(i)

        series = dict(
            zip(
                [i.instrument_key for i in members],
                await asyncio.gather(*(one(i) for i in members)),
                strict=True,
            )
        )
        bench_inst, vix_inst = self._index("NIFTY"), self._index("INDIA VIX")
        if bench_inst is None:
            raise AppError("NIFTY 50 is missing from the instrument master.")
        bench = await self._series(bench_inst)
        if bench is None:
            raise AppError("NIFTY 50 history is unavailable.")
        vix = await self._series(vix_inst) if vix_inst else None
        industries = {i.instrument_key: self._instruments.industry_of(i.isin) for i in members}
        sectors: dict[str, tuple[str, _Series | None]] = {}
        for name in {v for v in industries.values() if v}:
            mapped = SECTOR_INDEX.get(name)
            inst = self._index(mapped[1]) if mapped else None
            sectors[name] = (mapped[0], await self._series(inst)) if mapped and inst else ("", None)

        self._progress = "Loading macro series and annual statements"
        fred_rows: dict[str, list[tuple[date, float]]] = {}
        for spec in MACRO_SERIES:
            with contextlib.suppress(AppError):
                fred_rows[spec[0]] = await self._data.fred_history(spec[1])
        statements: dict[str, list] = {}
        stmt_failures = 0
        stmt_slots = asyncio.Semaphore(3)

        async def stmt(i: Instrument):
            async with stmt_slots:
                try:
                    return await self._data.statements(i.symbol)
                except AppError:
                    return None

        for i, rows in zip(members, await asyncio.gather(*(stmt(i) for i in members)), strict=True):
            if rows:
                statements[i.instrument_key] = rows
            else:
                stmt_failures += 1

        self._progress = "Replaying the agents month by month"
        # A separate process: the replay is minutes of pure-Python work, and in a thread it
        # would hold the interpreter lock and stall every other request.
        with ProcessPoolExecutor(max_workers=1) as pool:
            periods, meta = await asyncio.get_running_loop().run_in_executor(
                pool,
                SignalLab._replay,
                members,
                series,
                bench,
                vix,
                industries,
                sectors,
                fred_rows,
                statements,
            )
        self._record_live(meta.get("live"))
        tracking = await self._tracking()
        self._forward(tracking, series, members)
        tests = self._tests(periods, meta)
        usable = sum(
            1
            for s in series.values()
            if s and len(s.closes) >= MIN_HISTORY and suspicious_jump(s.closes) is None
        )
        jumpy = sum(
            1
            for s in series.values()
            if s and len(s.closes) >= MIN_HISTORY and suspicious_jump(s.closes)
        )
        dates = sorted(meta["dates"])
        headline = _headline(tests)
        return SignalValidation(
            computed_at=datetime.now(UTC),
            universe=UNIVERSE,
            stocks=usable,
            start=date.fromisoformat(dates[0]) if dates else None,
            end=date.fromisoformat(dates[-1]) if dates else None,
            horizon_sessions=HORIZON,
            tests=tests,
            untestable=UNTESTABLE,
            tracking=tracking,
            headline=headline,
            method=[
                "Each month's first session, every agent score is rebuilt from data dated on or "
                "before that session, then compared with the stock's return from the next "
                f"session over the following {HORIZON} sessions.",
                "Information coefficient (IC): the rank correlation between scores and those "
                "returns across the universe that month. Positive means higher scores came "
                "before better returns.",
                "The interval resamples blocks of three consecutive months (1,000 resamples, "
                "fixed seed). The spread is the top fifth by score minus the whole universe, "
                "after a 0.32% round-trip cost on the changed part of the top fifth.",
                f"Verdict rules fixed in advance: evidence needs {E.EVIDENCE_MONTHS}+ months, "
                f"|t| of at least {E.EVIDENCE_T}, an interval that excludes zero and the same "
                "sign in both halves of the history. The agents' formulas were not fitted to "
                "this data.",
            ],
            limitations=[
                f"The universe is today's {UNIVERSE}, so stocks that dropped out are missing. "
                "Rank correlations are less affected than returns, but not immune.",
                "Peers are up to 12 in-universe members of the same NSE industry, chosen "
                "alphabetically rather than by traded value as the live agent does; industries "
                "use today's classification.",
                "Statement ratios come from four annual reports at most, so the fundamental "
                "part of the Firm agent only enters from mid-2023 and uses annual rather than "
                "quarterly growth.",
                "FRED observations are taken as later revised, not as first published.",
                f"{jumpy} stocks left out for one-day moves over 35% (likely unadjusted corporate "
                "actions); one-month outcomes are capped at -60% and +100%.",
                f"Statement history unavailable for {stmt_failures} stocks."
                if stmt_failures
                else "Statement history loaded for every stock.",
                "Price returns, not total returns: dividends are excluded from the outcomes.",
            ],
            duration_ms=int((time.perf_counter() - started) * 1000),
        )

    @staticmethod
    def _replay(members, series, bench, vix, industries, sectors, fred_rows, statements):
        usable = [
            i
            for i in members
            if series.get(i.instrument_key)
            and len(series[i.instrument_key].closes) >= MIN_HISTORY
            and suspicious_jump(series[i.instrument_key].closes) is None
        ]
        by_industry: dict[str, list[Instrument]] = defaultdict(list)
        for i in usable:
            if industries.get(i.instrument_key):
                by_industry[industries[i.instrument_key]].append(i)
        starts = []
        prev_month = None
        for k, d in enumerate(bench.days):
            m = session_date(d).replace(day=1)
            if m != prev_month:
                prev_month = m
                if k >= MIN_HISTORY and k + 1 + HORIZON < len(bench.days):
                    starts.append(k)
        starts.append(len(bench.days) - 1)  # today: recorded for forward testing, no outcome yet
        periods: dict[str, list[E.Period]] = defaultdict(list)
        meta: dict = {"dates": set(), "first": {}, "market": []}
        for k in starts:
            day = bench.days[k]
            on = session_date(day)
            as_of = datetime(on.year, on.month, on.day, tzinfo=UTC)
            live = k == len(bench.days) - 1
            entry_day = bench.days[k + 1] if not live else None
            exit_day = bench.days[k + 1 + HORIZON] if not live else None
            known_macro = []
            for spec in MACRO_SERIES:
                rows = fred_rows.get(spec[0])
                if rows is None:
                    continue
                lag = SERIES_LAG.get(spec[0], DAILY_LAG)
                known_macro.append(macro_indicator(spec, [r for r in rows if r[0] + lag <= on], on))
            bench_s = bench.upto(day, as_of)
            vix_s = vix.upto(day, as_of) if vix else None
            fund_cache: dict[str, Fundamentals | None] = {}

            def fundamentals(i: Instrument, fund_cache=fund_cache, on=on):
                key = i.instrument_key
                if key not in fund_cache:
                    rows = statements.get(key)
                    fund_cache[key] = pit_fundamentals(i.symbol, rows, on) if rows else None
                return fund_cache[key]

            slices = {
                i.instrument_key: series[i.instrument_key].upto(day, as_of)
                for i in usable
                if series[i.instrument_key].count_upto(day) >= MIN_HISTORY
            }
            scores: dict[str, dict[str, float]] = defaultdict(dict)
            forward: dict[str, float] = {}
            for i in usable:
                stock = slices.get(i.instrument_key)
                if stock is None:
                    continue
                s = series[i.instrument_key]
                a = s.close_on(entry_day) if entry_day else None
                b = s.close_on(exit_day) if exit_day else None
                if a and b:
                    forward[i.symbol] = min(OUTCOME_CAP[1], max(OUTCOME_CAP[0], b / a - 1))
                ind = industries.get(i.instrument_key)
                ctx = ResearchContext(instrument=i, now=as_of)
                ctx.stock, ctx.benchmark, ctx.vix, ctx.macro = stock, bench_s, vix_s, known_macro
                ctx.fundamentals = fundamentals(i)
                if ctx.fundamentals is None:
                    ctx.problems["fundamentals"] = "no annual statements known yet"
                ctx.industry = ind
                if ind:
                    label, sec = sectors.get(ind, ("", None))
                    if sec is not None:
                        ctx.sector_label = label
                        ctx.sector = sec.upto(day, as_of)
                    peers = [p for p in by_industry[ind] if p.instrument_key != i.instrument_key]
                    ctx.peers = [
                        Peer(p, slices.get(p.instrument_key), fundamentals(p))
                        for p in sorted(peers, key=lambda p: p.symbol)[:MAX_PEERS]
                    ]
                outputs = [firm.run(ctx), industry.run(ctx), macro.run(ctx)]
                comp = composite(outputs)
                if comp.score is not None:
                    scores["composite"][i.symbol] = comp.score
                for o in outputs:
                    if o.score is not None:
                        scores[o.agent][i.symbol] = o.score
                    for f in o.factors:
                        if f.score is not None and f.weight > 0:
                            scores[f"{o.agent}:{f.name}"][i.symbol] = f.score
            iso = on.isoformat()
            if live:
                meta["live"] = (on, {key: dict(v) for key, v in scores.items()})
                continue
            meta["dates"].add(iso)
            regime = scores.pop("macro:Market regime", {})
            a = bench.close_on(entry_day) if entry_day else None
            b = bench.close_on(exit_day) if exit_day else None
            if regime and a and b:
                meta["market"].append((iso, next(iter(regime.values())), b / a - 1))
            for key, sc in scores.items():
                periods[key].append(E.Period(iso, sc, forward))
                meta["first"].setdefault(key, iso)
        return periods, meta

    def _tests(self, periods, meta) -> list[SignalTest]:
        out = []
        order = ["composite", "firm", "industry", "macro"]
        keys = order + sorted(k for k in periods if k not in order)
        for key in keys:
            ps = periods.get(key)
            if not ps:
                continue
            s = E.summarize(ps)
            out.append(self._test(key, s, E.ic_series(ps)))
        if meta["market"]:
            s = E.timing_summary(meta["market"])
            dates = [d for d, _, _ in meta["market"]]
            t = self._test("macro:Market regime", s, [])
            t.label = "Macro: market regime (timing)"
            t.inputs = "Same for every stock on a date, so tested against the NIFTY 50's next month"
            t.first_date, t.last_date = date.fromisoformat(dates[0]), date.fromisoformat(dates[-1])
            out.append(t)
        return out

    def _test(self, key: str, s: E.Summary, ics) -> SignalTest:
        if key == "composite":
            label, agent, kind, inputs = (
                "Combined research score",
                "composite",
                "composite",
                "Firm, Industry and Macro as replayed; Sentiment has no history",
            )
        elif key in AGENTS:
            label, inputs = AGENTS[key]
            agent, kind = key, "agent"
        else:
            agent, name = key.split(":", 1)
            label, kind, inputs = f"{AGENTS[agent][0].split(' (')[0]}: {name}", "factor", ""
        return SignalTest(
            key=key,
            label=label,
            agent=agent,
            kind=kind,  # type: ignore[arg-type]
            inputs=inputs,
            months=s.months,
            avg_stocks=round(s.avg_stocks, 1),
            first_date=date.fromisoformat(ics[0][0]) if ics else None,
            last_date=date.fromisoformat(ics[-1][0]) if ics else None,
            mean_ic=s.mean_ic,
            ic_t=s.ic_t,
            ic_low=s.ic_low,
            ic_high=s.ic_high,
            hit_rate=s.hit_rate,
            first_half_ic=s.first_half,
            second_half_ic=s.second_half,
            spread_annual=s.spread_annual,
            spread_t=s.spread_t,
            by_year=[YearIC(year=y, ic=v, months=n) for y, v, n in s.by_year],
            verdict=s.verdict,  # type: ignore[arg-type]
            verdict_text=s.verdict_text,
        )

    def _record_live(self, live) -> None:
        """Store today's replayable scores so later runs can test them on returns that did
        not exist when they were recorded."""
        if not live:
            return
        on, scores = live
        now = datetime.now(UTC)
        for key, by_symbol in scores.items():
            for sym, score in by_symbol.items():
                self._db.execute(
                    "INSERT OR IGNORE INTO forward_signals VALUES (?, ?, ?, ?, ?)",
                    [on, sym, key, score, now],
                )

    def _forward(self, tracking: ForwardTracking, series, members) -> None:
        rows = self._db.fetchall(
            "SELECT snapshot_date, symbol, signal_key, score FROM forward_signals "
            "ORDER BY snapshot_date"
        )
        if not rows:
            return
        by_symbol = {
            i.symbol: series.get(i.instrument_key) for i in members if series.get(i.instrument_key)
        }
        snapshots: dict = defaultdict(lambda: defaultdict(dict))
        for d, sym, key, score in rows:
            snapshots[d][key][sym] = float(score)
        tracking.recorded_snapshots = len(snapshots)
        tracking.first_recorded = min(snapshots)
        periods: dict[str, list[E.Period]] = defaultdict(list)
        scored = 0
        spaced = []  # non-overlapping outcomes: snapshots at least four weeks apart
        for d in sorted(snapshots):
            if not spaced or (d - spaced[-1]).days >= 28:
                spaced.append(d)
        for d in spaced:
            keys = snapshots[d]
            day = (d - date(1970, 1, 1)).days - 1
            forward: dict[str, float] = {}
            for sym, s in by_symbol.items():
                i = s.count_upto(day)
                if 0 < i and i + HORIZON < len(s.closes):
                    forward[sym] = s.closes[i + HORIZON] / s.closes[i] - 1
            if not forward:
                continue
            scored += 1
            for key, sc in keys.items():
                periods[key].append(E.Period(d.isoformat(), sc, forward))
        tracking.scored_snapshots = scored
        out = []
        for key in ("composite", "firm", "industry", "macro"):
            ps = periods.get(key, [])
            summ = E.summarize(ps) if ps else None
            label = "Combined research score" if key == "composite" else AGENTS[key][0]
            out.append(
                ForwardSignal(
                    key=key,
                    label=label,
                    snapshots=summ.months if summ else 0,
                    mean_ic=summ.mean_ic if summ else None,
                    verdict=summ.verdict if summ else "insufficient",  # type: ignore[arg-type]
                )
            )
        tracking.recorded = out

    async def _tracking(self) -> ForwardTracking:
        """Pooled rank correlation between stored live scores and the next 21 sessions."""
        rows = self._db.fetchall(
            "SELECT instrument_key, computed_at, payload FROM research_history ORDER BY computed_at"
        )
        if not rows:
            return ForwardTracking(
                snapshots=0,
                with_outcomes=0,
                months_covered=0,
                first_snapshot=None,
                outcomes_from=None,
                pooled_ic=None,
                by_agent={},
                status="No stored research yet.",
            )
        pairs: dict[str, list[tuple[float, float]]] = defaultdict(list)
        months: set[str] = set()
        cache: dict[str, _Series | None] = {}
        first = _as_utc(rows[0][1])
        for key, at, payload in rows:
            if key not in cache:
                try:
                    cache[key] = await self._series(self._instruments.get(key))
                except AppError:
                    cache[key] = None
            s = cache[key]
            if s is None:
                continue
            day = (to_ist(_as_utc(at)).date() - date(1970, 1, 1)).days - 1
            i = bisect.bisect_right(s.days, day)
            if i + HORIZON >= len(s.closes) or i == 0:
                continue
            fwd = s.closes[i + HORIZON] / s.closes[i] - 1
            rep = ResearchReport.model_validate(json.loads(payload))
            months.add(f"{at:%Y-%m}")
            if rep.composite.score is not None:
                pairs["composite"].append((rep.composite.score, fwd))
            for a in rep.agents:
                if a.score is not None:
                    pairs[a.agent].append((a.score, fwd))
        n = len(pairs["composite"])
        ready = n >= TRACK_MIN_PAIRS and len(months) >= TRACK_MIN_MONTHS

        def ic(key: str) -> float | None:
            p = pairs.get(key, [])
            return E.spearman([x for x, _ in p], [y for _, y in p]) if len(p) >= 10 else None

        outcomes_from = (to_ist(first) + timedelta(days=32)).date()
        status = (
            f"{n} scored reports have a known 21-session outcome across {len(months)} months."
            if ready
            else f"Collecting: {len(rows)} stored reports, {n} with a known outcome so far. "
            f"A first reading needs {TRACK_MIN_PAIRS} outcomes across {TRACK_MIN_MONTHS} "
            "months; outcomes start arriving about a month after each report."
        )
        return ForwardTracking(
            snapshots=len(rows),
            with_outcomes=n,
            months_covered=len(months),
            first_snapshot=first,
            outcomes_from=outcomes_from,
            pooled_ic=ic("composite") if ready else None,
            by_agent={a: ic(a) for a in ("firm", "industry", "macro", "sentiment")}
            if ready
            else {},
            status=status,
        )


def _headline(tests: list[SignalTest]) -> str:
    main = {t.key: t for t in tests if t.kind != "factor"}
    good = [t.label for t in main.values() if t.verdict == "evidence"]
    bad = [t.label for t in main.values() if t.verdict == "negative"]
    if good:
        return (
            f"{', '.join(good)} showed measurable value in the replay; the rest did not clear "
            "the bar."
        )
    if bad:
        return f"{', '.join(bad)} pointed the wrong way in the replay; none showed reliable value."
    comp = main.get("composite")
    if comp and comp.mean_ic is not None:
        near = [
            t
            for t in tests
            if t.ic_t is not None
            and t.ic_t >= 2.0
            and t.ic_low is not None
            and t.ic_low > 0
            and (t.first_half_ic or 0) > 0
            and (t.second_half_ic or 0) > 0
        ]
        text = (
            "No research signal has shown reliable predictive value yet. Treat scores as "
            "organised evidence, not forecasts."
        )
        if near:
            names = ", ".join(t.label for t in near[:3])
            text += (
                f" Closest to the bar: {names} (positive in both halves, but short of the "
                "pre-set strength; forward testing will tell)."
            )
        return text
    return "Not enough history to judge the research signals yet."
