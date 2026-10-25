"""Portfolio intelligence: weights, risk, walk-forward validation, candidate discovery, and
interactive plans for an investor objective.

The analysis covers the whole watchlist. It runs in the background (it may fetch about a
hundred price histories for the candidate screen), is stored in DuckDB, and is re-run when the
watchlist changes or the stored analysis ages past the refresh window. Plans reuse the price
and dividend data the analysis loaded and answer in about a second.
"""

import asyncio
import contextlib
import hashlib
import json
import logging
import random
import statistics
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.db import Database, _as_utc
from app.errors import AppError, NotFound
from app.schemas.market import Instrument
from app.schemas.plan import HoldingIn, HoldingOut, PortfolioPlan, Preferences
from app.schemas.portfolio import (
    BacktestResult,
    Candidate,
    Correlation,
    Excluded,
    Holding,
    ObjectivePreview,
    PortfolioAnalysis,
    PortfolioStatus,
    Replacement,
    SelectionCheck,
    StrategyResult,
    StrategyWeight,
    Validation,
)
from app.services import planner
from app.services.instruments import InstrumentService
from app.services.planner import AssetData, Prepared, curve, day_to_date, perf
from app.services.research import ResearchService
from app.services.research_data import ResearchData
from app.tools import backtest as B
from app.tools import portfolio as P
from app.tools.objectives import OBJECTIVES

log = logging.getLogger(__name__)

LOOKBACK = planner.LOOKBACK  # estimation window, sessions
MIN_HISTORY = planner.MIN_HISTORY  # sessions a holding needs to be included
COSTS = planner.COSTS
SECTOR_CAP = 0.40
CANDIDATE_UNIVERSE = "NIFTY 100"
TOP_CANDIDATES = 8
MAX_PER_SECTOR = 2
VALIDATED = 5
RESEARCH_CANDIDATES = 3
REFRESH_AFTER = timedelta(hours=6)
REFERENCE = "risk_parity"
RANDOM_PORTFOLIOS = 200
ASSET_TTL = timedelta(minutes=30)
PLAN_CACHE = 24
BENCH_ETF = "NIFTYBEES"
PREFS_KEY = "portfolio.preferences"


@dataclass(frozen=True)
class Strategy:
    key: str
    label: str
    description: str
    backtestable: bool


STRATEGIES = [
    Strategy("equal_weight", "Equal weight", "Baseline: the same weight in every holding.", True),
    Strategy(
        "inverse_vol",
        "Inverse volatility",
        "Weights proportional to 1 / volatility; ignores correlations.",
        True,
    ),
    Strategy(
        "min_variance",
        "Minimum variance",
        "Lowest estimated volatility from the shrunk covariance matrix, within the caps.",
        True,
    ),
    Strategy(
        "risk_parity",
        "Equal risk contribution",
        "Each holding contributes the same share of estimated portfolio risk.",
        True,
    ),
    Strategy(
        "research_tilt",
        "Research-tilted",
        "Equal risk contribution scaled by (1 + 0.5 x research composite x confidence).",
        False,
    ),
]


def stock_cap(n: int) -> float:
    return min(1.0, max(0.25, 1.5 / n))


def weights_for(key: str, S: P.Matrix, sectors: list[str], scores: list[float | None]):
    """Weights for one strategy with per-stock and sector caps. Returns (weights, ok, note)."""
    n = len(S)
    cap = stock_cap(n)
    distinct = len(set(sectors))
    group_cap = SECTOR_CAP if distinct >= 3 else 1.0
    if key == "equal_weight":
        raw = P.equal_weight(S)
    elif key == "inverse_vol":
        raw = P.inverse_volatility(S)
    elif key == "min_variance":
        raw = P.minimum_variance(S, cap)
    elif key == "risk_parity":
        raw = P.risk_parity(S)
    else:
        raw = P.score_tilt(P.risk_parity(S), scores)
    w, ok = P.apply_caps(raw, cap, sectors if distinct >= 3 else None, group_cap)
    note = None
    if not ok:
        note = "Caps could not all be met with these holdings; closest weights shown."
    elif distinct < 3:
        note = f"Sector cap not applied: holdings span {distinct} sector(s)."
    return w, ok, note


def _strategy_fn(key: str, sectors: list[str]):
    return lambda W, t: weights_for(key, P.shrunk_covariance(W)[0], sectors, [None] * len(W))[0]


class PortfolioService:
    def __init__(
        self,
        db: Database,
        instruments: InstrumentService,
        data: ResearchData,
        research: ResearchService,
        watchlist_keys: Callable[[], list[str]],
    ):
        self._db = db
        self._instruments = instruments
        self._data = data
        self._research = research
        self._watchlist_keys = watchlist_keys
        self._state: tuple[str, str | None] = ("not_started", None)
        self._task: asyncio.Task | None = None
        self._assets: dict[str, tuple[AssetData, datetime]] = {}
        self._plans: OrderedDict[str, PortfolioPlan] = OrderedDict()
        self._plan_lock = asyncio.Lock()

    # --- job control ---------------------------------------------------------------

    def _signature(self) -> str:
        return hashlib.sha1("|".join(sorted(self._watchlist_keys())).encode()).hexdigest()

    def request_run(self, force: bool = False) -> None:
        if self._task is not None and not self._task.done():
            return
        if not force and not self._is_stale():
            return
        self._state = ("queued", None)
        self._task = asyncio.create_task(self._job())

    @property
    def state(self) -> tuple[str, str | None]:
        return self._state

    async def _job(self) -> None:
        self._state = ("running", None)
        try:
            await self._instruments.ready.wait()
            result = await self.analyse()
            self._db.execute(
                "INSERT OR REPLACE INTO portfolio_runs VALUES ('latest', ?, ?, ?)",
                [self._signature(), result.model_dump_json(), result.computed_at],
            )
            self._plans.clear()
            self._state = ("ready", None)
        except AppError as exc:
            self._state = ("failed", exc.message)
        except Exception:
            log.exception("portfolio analysis failed")
            self._state = ("failed", "The portfolio analysis failed unexpectedly.")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    def _stored(self) -> tuple[str, str, datetime] | None:
        row = self._db.fetchone(
            "SELECT signature, payload, computed_at FROM portfolio_runs WHERE id = 'latest'"
        )
        return (row[0], row[1], _as_utc(row[2])) if row else None

    def _is_stale(self) -> bool:
        stored = self._stored()
        if stored is None:
            return True
        sig, _, at = stored
        return sig != self._signature() or datetime.now(UTC) - at > REFRESH_AFTER

    def latest(self) -> PortfolioAnalysis | None:
        stored = self._stored()
        if stored is None:
            return None
        try:
            return PortfolioAnalysis.model_validate(json.loads(stored[1]))
        except ValueError:  # stored by an older version with a different shape
            return None

    def status(self) -> PortfolioStatus:
        result = self.latest()
        state, error = self._state
        if state == "not_started" and result is not None:
            state = "ready"
        return PortfolioStatus(state=state, error=error, stale=self._is_stale(), result=result)  # type: ignore[arg-type]

    # --- data ----------------------------------------------------------------------

    def _sector(self, i: Instrument) -> str:
        return self._instruments.industry_of(i.isin) or "Unclassified"

    def _research_of(self, key: str) -> tuple[str, float | None, float | None] | None:
        report = self._research.latest(key)
        if report is None:
            return None
        c = report.composite
        return c.signal, c.score, c.confidence

    async def _asset(self, inst: Instrument, role: str = "holding", divs: bool = True) -> AssetData:
        """Ten years of daily closes plus dividends; cached in memory for plan requests."""
        hit = self._assets.get(inst.instrument_key)
        now = datetime.now(UTC)
        if hit and now - hit[1] < ASSET_TTL and (hit[0].dividends is not None or not divs):
            a = hit[0]
        else:
            series = await self._data.long_daily(inst)
            dividends = None
            if divs:
                try:
                    dividends = await self._data.dividends(inst.symbol)
                except AppError as exc:
                    log.info("dividends unavailable for %s: %s", inst.symbol, exc.message)
            a = AssetData(inst, self._sector(inst), series, dividends)
            self._assets[inst.instrument_key] = (a, now)
        return AssetData(
            a.inst, a.sector, a.series, a.dividends, self._research_of(inst.instrument_key), role
        )

    async def _assets_for(
        self, instruments: list[Instrument], role: str = "holding", divs: bool = True
    ) -> dict[str, AssetData | str]:
        slots = asyncio.Semaphore(8)

        async def one(i: Instrument) -> AssetData | str:
            async with slots:
                try:
                    return await self._asset(i, role, divs)
                except AppError as exc:
                    return exc.message

        results = await asyncio.gather(*(one(i) for i in instruments))
        return {i.instrument_key: r for i, r in zip(instruments, results, strict=True)}

    async def _benchmark(self) -> tuple[AssetData, str, str]:
        """NIFTY 50 total-return proxy: the NIFTYBEES ETF (its price keeps the index dividends,
        net of fund costs). Falls back to the NIFTY 50 price index."""
        with contextlib.suppress(AppError):
            etf = await self._asset(self._instruments.by_symbol(BENCH_ETF), "benchmark")
            if (
                len(etf.series.closes) >= MIN_HISTORY
                and P.suspicious_jump(etf.series.closes) is None
            ):
                return (
                    etf,
                    "NIFTY 50 (NIFTYBEES ETF)",
                    "NIFTY 50 benchmark: NIFTYBEES ETF, whose price retains the index dividends "
                    "net of fund costs, plus any distributions on record.",
                )
        try:
            index = self._instruments.by_symbol("NIFTY", "NSE_INDEX")
        except NotFound as exc:
            raise AppError("NIFTY 50 is missing from the instrument master.") from exc
        try:
            a = await self._asset(index, "benchmark", divs=False)
        except AppError as exc:
            raise AppError(f"NIFTY 50 history unavailable: {exc.message}") from exc
        a.dividends = []
        return a, "NIFTY 50 (price index)", "NIFTY 50 benchmark: price index without dividends."

    async def _risk_free(self) -> tuple[float, str]:
        for m in await self._data.macro():
            if m.key == "in10y" and m.value is not None and not m.stale:
                return m.value / 100, f"India 10Y government bond yield, {m.source}"
        return 0.0, "Unavailable; Sharpe ratios use a 0% risk-free rate"

    def _watch_equities(self) -> tuple[list[Instrument], list[Excluded]]:
        keys = self._watchlist_keys()
        found = self._instruments.get_many(keys)
        members = [found[k] for k in keys if k in found]
        excluded = [
            Excluded(symbol=i.symbol, reason="Indices are not investable here.")
            for i in members
            if i.segment != "NSE_EQ"
        ]
        return [i for i in members if i.segment == "NSE_EQ"], excluded

    # --- analysis ------------------------------------------------------------------

    async def analyse(self) -> PortfolioAnalysis:
        started = time.perf_counter()
        limitations: list[str] = []
        equities, excluded = self._watch_equities()
        bench, bench_label, bench_note = await self._benchmark()
        fetched = await self._assets_for(equities)
        assets: list[AssetData] = []
        for i in equities:
            a = fetched[i.instrument_key]
            if isinstance(a, str):
                excluded.append(Excluded(symbol=i.symbol, reason=f"Price history unavailable: {a}"))
            else:
                assets.append(a)
        prep = planner.prepare(assets, bench)
        excluded += prep.excluded
        rf, rf_source = await self._risk_free()
        holdings, strategies, correlation, previews = await asyncio.to_thread(
            self._analyse_sync, prep, rf, limitations
        )

        candidates: list[Candidate] = []
        replacements: list[Replacement] = []
        screened = 0
        selection = None
        if prep.assets and len(prep.days) > LOOKBACK + 1:
            candidates, replacements, screened, selection = await self._discover(
                prep, holdings, rf, limitations
            )
        elif prep.assets:
            limitations.append("Holdings share too few common sessions for a risk estimate.")

        return PortfolioAnalysis(
            computed_at=datetime.now(UTC),
            as_of=day_to_date(prep.days[-1]) if prep.days else None,
            holdings=holdings,
            excluded=excluded,
            strategies=strategies,
            reference_strategy=REFERENCE,
            correlation=correlation,
            candidates=candidates,
            candidate_universe=CANDIDATE_UNIVERSE,
            candidates_screened=screened,
            replacements=replacements,
            risk_free_rate=rf,
            risk_free_source=rf_source,
            assumptions=[
                f"Costs per trade: buy {COSTS.buy_rate:.3%}, sell {COSTS.sell_rate:.3%} of value "
                f"plus Rs {COSTS.dp_per_sell:.2f} per stock sold: STT, stamp duty, exchange, "
                "SEBI and GST at 2025 rates, zero brokerage and 0.05% assumed slippage.",
                "Backtests start from cash and rebalance at the close of the first session of "
                f"each month using only the {LOOKBACK} sessions before that day.",
                f"Long only, fully invested. Stock cap = max(25%, 1.5 / holdings); sector cap "
                f"{SECTOR_CAP:.0%} when holdings span three or more sectors.",
                "Total returns: Upstox daily closes (split and bonus adjusted) plus cash "
                "dividends from Yahoo Finance, reinvested at the next rebalance. Pre-tax.",
                bench_note,
                f"Candidates: {CANDIDATE_UNIVERSE} stocks ranked on the trailing year (40% "
                "diversification ratio, 40% volatility, 20% in-sample Sharpe) with equal risk "
                f"contribution weights; the top {VALIDATED} are re-tested by walk-forward on the "
                "earlier, non-overlapping period.",
            ],
            limitations=limitations
            + prep.notes
            + ([prep.limited_by] if prep.limited_by else [])
            + [
                "Survivorship and selection bias: the backtest uses stocks chosen today, so "
                "historical results flatter the strategies. The selection check compares your "
                "picks with random portfolios drawn from the same surviving universe.",
                "Trailing one-year figures are in-sample estimates, not forecasts.",
            ],
            duration_ms=int((time.perf_counter() - started) * 1000),
            benchmark_label=bench_label,
            return_basis="Total return (dividends reinvested), after trading costs, before tax",
            objectives=previews,
            selection=selection,
        )

    def _analyse_sync(self, prep: Prepared, rf: float, limitations: list[str]):
        holdings = [self._holding(a, len(a.series.closes)) for a in prep.assets]
        strategies: list[StrategyResult] = []
        correlation = None
        previews: list[ObjectivePreview] = []
        n = len(prep.assets)
        if 2 <= n < 5:
            limitations.append(
                f"With {n} holdings the strategies differ little and risk estimates depend "
                "heavily on each stock; the candidate screen below matters more."
            )
        if n < 2:
            limitations.append(
                "At least two watchlist stocks with 15 months of clean price history are needed "
                "to build and compare portfolios."
            )
        if n and len(prep.days) > LOOKBACK + 1:
            tr = [B.total_return_index(c, d) for c, d in zip(prep.closes, prep.divs, strict=True)]
            R = [P.simple_returns(x)[-LOOKBACK:] for x in tr]
            S, shrink = P.shrunk_covariance(R)
            sectors = [h.sector for h in holdings]
            scores = [
                (h.research_score * h.research_confidence)
                if h.research_score is not None and h.research_confidence is not None
                else None
                for h in holdings
            ]
            if n >= 2:
                corr = P.correlation(S)
                off = [corr[a][b] for a in range(n) for b in range(n) if a < b]
                correlation = Correlation(
                    symbols=[h.symbol for h in holdings],
                    matrix=[[round(x, 3) for x in row] for row in corr],
                    average=round(statistics.fmean(off), 3) if off else None,
                )
                strategies = [
                    self._strategy(st, prep, holdings, S, R, sectors, scores, rf)
                    for st in STRATEGIES
                ]
                if all(s is None for s in scores):
                    limitations.append(
                        "No research reports yet, so the research-tilted portfolio equals equal "
                        "risk contribution."
                    )
            limitations.append(
                f"Covariance estimated from the last {LOOKBACK} sessions with Ledoit-Wolf "
                f"shrinkage (intensity {shrink:.2f})."
            )
            previews = [planner.preview(prep, key, rf, 1_000_000.0, 0.30) for key in OBJECTIVES]
        return holdings, strategies, correlation, previews

    def _holding(self, a: AssetData, history: int) -> Holding:
        r = a.research
        return Holding(
            symbol=a.inst.symbol,
            name=a.inst.name,
            instrument_key=a.inst.instrument_key,
            sector=a.sector,
            history_days=history,
            research_signal=r[0] if r else None,
            research_score=r[1] if r else None,
            research_confidence=r[2] if r else None,
        )

    def _strategy(self, st, prep: Prepared, holdings, S, R, sectors, scores, rf) -> StrategyResult:
        w, ok, note = weights_for(st.key, S, sectors, scores)
        rc = P.risk_contributions(w, S)
        sector_w: dict[str, float] = {}
        for sec, x in zip(sectors, w, strict=True):
            sector_w[sec] = round(sector_w.get(sec, 0.0) + x, 4)
        trailing = P.fixed_weight_returns(R, w)
        backtest = None
        bt_note = None
        if st.backtestable:
            sim = B.simulate(
                prep.days, prep.closes, prep.divs, _strategy_fn(st.key, sectors), LOOKBACK, COSTS
            )
            if sim is None:
                bt_note = "Not enough history for a walk-forward test."
            else:
                backtest = self._backtest(sim, prep, rf)
        else:
            bt_note = (
                "Not backtested: research scores have a point-in-time history only from the "
                "day research began, so any backtest would use information that was not "
                "available then."
            )
        return StrategyResult(
            key=st.key,
            label=st.label,
            description=st.description,
            weights=[
                StrategyWeight(symbol=h.symbol, weight=round(x, 4), risk_contribution=round(r, 4))
                for h, x, r in zip(holdings, w, rc, strict=True)
            ],
            sector_weights=sector_w,
            est_volatility=P.port_vol(w, S),
            diversification_ratio=P.diversification_ratio(w, S),
            effective_n=P.effective_n(w),
            trailing=perf(trailing, prep.days, len(prep.days) - len(trailing), rf),
            constraints_met=ok,
            constraint_note=note,
            backtest=backtest,
            backtest_note=bt_note,
        )

    def _backtest(self, sim: B.Simulation, prep: Prepared, rf: float) -> BacktestResult:
        start = sim.start_index
        bench_daily = planner.bench_run(prep, start)
        years = len(sim.daily) / P.TRADING_DAYS or 1
        return BacktestResult(
            stats=perf(sim.daily, prep.days, start, rf),
            benchmark=perf(bench_daily, prep.days, start, rf),
            rebalances=sim.rebalances,
            turnover_per_year=sim.turnover / years,
            cost_drag_per_year=sim.costs / years,
            curve=curve(prep.days, sim.equity, start),
            benchmark_curve=curve(prep.days, planner.equity(bench_daily), start),
        )

    # --- candidates --------------------------------------------------------------------

    async def _discover(self, prep: Prepared, holdings: list[Holding], rf, limitations):
        held = {a.inst.instrument_key for a in prep.assets} | set(self._watchlist_keys())
        pool = [
            i
            for i in self._instruments.constituents(CANDIDATE_UNIVERSE)
            if i.instrument_key not in held
        ]
        if not pool:
            limitations.append(f"{CANDIDATE_UNIVERSE} constituents unavailable; no candidates.")
            return [], [], 0, None
        series = await self._assets_for(pool, "added", divs=False)
        rows, skipped = await asyncio.to_thread(self._screen, prep, holdings, pool, series, rf)
        if skipped:
            limitations.append(
                f"{skipped} of {len(pool)} {CANDIDATE_UNIVERSE} stocks skipped for missing or "
                "short price history."
            )
        selection = await asyncio.to_thread(self._selection, prep, pool, series)
        if not rows:
            return [], [], 0, selection
        top = self._pick(rows)
        for r in top[:RESEARCH_CANDIDATES]:
            self._research.enqueue(r["inst"].instrument_key)
        # Dividends for the validated candidates so the out-of-sample test uses total returns.
        validated = await self._assets_for([r["inst"] for r in top[:VALIDATED]], "added")
        candidates = await asyncio.to_thread(
            self._candidates, prep, holdings, top, validated, rows[0], rf
        )
        replacements = (
            await asyncio.to_thread(self._replacements, prep, holdings, top[:3])
            if len(prep.assets) >= 2
            else []
        )
        return candidates, replacements, len(rows), selection

    def _screen(self, prep: Prepared, holdings, pool, series, rf):
        n = len(prep.assets)
        base_sectors = [h.sector for h in holdings]
        hold_map = {a.inst.instrument_key: a.series.pairs for a in prep.assets}
        tr = [B.total_return_index(c, d) for c, d in zip(prep.closes, prep.divs, strict=True)]
        R_base = [P.simple_returns(x)[-LOOKBACK:] for x in tr]
        S_base, _ = P.shrunk_covariance(R_base)
        w_base, _, _ = weights_for(REFERENCE, S_base, base_sectors, [None] * n)
        base = {
            "vol": P.port_vol(w_base, S_base),
            "dr": P.diversification_ratio(w_base, S_base),
            "sharpe": P.stats(P.fixed_weight_returns(R_base, w_base), rf).sharpe,
        }
        rows = []
        skipped = 0
        for inst in pool:
            s = series[inst.instrument_key]
            if (
                isinstance(s, str)
                or len(s.series.closes) < MIN_HISTORY
                or P.suspicious_jump(s.series.closes[-LOOKBACK * 2 :])
            ):
                skipped += 1
                continue
            d, al = P.align(hold_map | {"__c": s.series.pairs})
            if len(d) <= LOOKBACK + 1:
                skipped += 1
                continue
            R = [P.simple_returns(al[a.inst.instrument_key])[-LOOKBACK:] for a in prep.assets]
            rc = P.simple_returns(al["__c"])[-LOOKBACK:]
            S, _ = P.shrunk_covariance([*R, rc])
            w, _, _ = weights_for(REFERENCE, S, [*base_sectors, s.sector], [None] * (n + 1))
            corr = P.correlation(S)
            rows.append(
                {
                    "inst": inst,
                    "sector": s.sector,
                    "avg_corr": statistics.fmean(corr[n][j] for j in range(n)),
                    "vol": (S[n][n] * P.TRADING_DAYS) ** 0.5,
                    "w": w[n],
                    "vol_after": P.port_vol(w, S),
                    "dr_after": P.diversification_ratio(w, S),
                    "sharpe_after": P.stats(P.fixed_weight_returns([*R, rc], w), rf).sharpe,
                    "base": base,
                }
            )

        def ranks(values: list[float], descending: bool) -> list[float]:
            order = sorted(range(len(values)), key=lambda k: values[k], reverse=descending)
            out = [0.0] * len(values)
            for pos, k in enumerate(order):
                out[k] = 1 - pos / max(1, len(values) - 1)
            return out

        if rows:
            r_dr = ranks([r["dr_after"] for r in rows], True)
            r_vol = ranks([r["vol_after"] for r in rows], False)
            r_sh = ranks(
                [r["sharpe_after"] if r["sharpe_after"] is not None else -9 for r in rows], True
            )
            for k, r in enumerate(rows):
                r["score"] = 0.4 * r_dr[k] + 0.4 * r_vol[k] + 0.2 * r_sh[k]
            rows.sort(key=lambda r: (-r["score"], r["inst"].symbol))
        return rows, skipped

    @staticmethod
    def _pick(rows: list[dict]) -> list[dict]:
        top: list[dict] = []
        per_sector: dict[str, int] = {}
        for r in rows:  # at most MAX_PER_SECTOR names per sector keeps the list diverse
            if per_sector.get(r["sector"], 0) < MAX_PER_SECTOR:
                top.append(r)
                per_sector[r["sector"]] = per_sector.get(r["sector"], 0) + 1
            if len(top) == TOP_CANDIDATES:
                break
        return top

    def _candidates(self, prep, holdings, top, validated, first, rf) -> list[Candidate]:
        base_sectors = [h.sector for h in holdings]
        base = first["base"]
        out = []
        for k, r in enumerate(top):
            inst = r["inst"]
            v = validated.get(inst.instrument_key) if k < VALIDATED else None
            validation = (
                self._validate(prep, base_sectors, v, rf) if isinstance(v, AssetData) else None
            )
            research = self._research_of(inst.instrument_key)
            new_sector = r["sector"] not in base_sectors
            explanation = (
                f"Average correlation {r['avg_corr']:.2f} with current holdings"
                f"{'; adds a new sector (' + r['sector'] + ')' if new_sector else ''}. "
                f"At {r['w']:.0%} weight, estimated volatility moves {base['vol']:.1%} to "
                f"{r['vol_after']:.1%} and the diversification ratio {base['dr']:.2f} to "
                f"{r['dr_after']:.2f}."
            )
            if validation and validation.vol_with is not None and validation.vol_without:
                verb = "lower" if validation.vol_with < validation.vol_without else "higher"
                explanation += (
                    f" In the earlier period ({validation.start:%b %Y} to {validation.end:%b %Y}) "
                    f"adding it gave {verb} measured volatility "
                    f"({validation.vol_without:.1%} to {validation.vol_with:.1%})."
                )
            out.append(
                Candidate(
                    symbol=inst.symbol,
                    name=inst.name,
                    instrument_key=inst.instrument_key,
                    sector=r["sector"],
                    new_sector=new_sector,
                    avg_correlation=round(r["avg_corr"], 3),
                    volatility=r["vol"],
                    weight_if_added=r["w"],
                    vol_before=base["vol"],
                    vol_after=r["vol_after"],
                    dr_before=base["dr"],
                    dr_after=r["dr_after"],
                    sharpe_before=base["sharpe"],
                    sharpe_after=r["sharpe_after"],
                    rank_score=round(r["score"], 3),
                    validation=validation,
                    research_signal=research[0] if research else None,
                    research_score=research[1] if research else None,
                    explanation=explanation,
                )
            )
        return out

    def _validate(self, prep: Prepared, base_sectors, cand: AssetData, rf) -> Validation | None:
        """Walk-forward with and without the candidate on sessions before the screen window,
        on total returns and after costs."""
        with_c = planner.prepare([*prep.assets, cand], prep.bench)
        if len(with_c.assets) != len(prep.assets) + 1:
            return None
        d = with_c.days
        end = len(d) - LOOKBACK
        if end <= LOOKBACK + 42:
            return None
        n = len(prep.assets)
        sectors = [*base_sectors, cand.sector]
        without = B.simulate(
            d,
            with_c.closes[:n],
            with_c.divs[:n],
            _strategy_fn(REFERENCE, base_sectors),
            LOOKBACK,
            COSTS,
            end=end,
        )
        added = B.simulate(
            d,
            with_c.closes,
            with_c.divs,
            _strategy_fn(REFERENCE, sectors),
            LOOKBACK,
            COSTS,
            end=end,
        )
        if without is None or added is None:
            return None
        a, b = P.stats(without.daily, rf), P.stats(added.daily, rf)
        return Validation(
            start=day_to_date(d[without.start_index]),
            end=day_to_date(d[end - 1]),
            vol_without=a.volatility,
            vol_with=b.volatility,
            sharpe_without=a.sharpe,
            sharpe_with=b.sharpe,
            mdd_without=a.max_drawdown,
            mdd_with=b.max_drawdown,
        )

    def _replacements(self, prep: Prepared, holdings, top) -> list[Replacement]:
        out = []
        n = len(prep.assets)
        hold_map = {a.inst.instrument_key: a.series.pairs for a in prep.assets}
        for r in top:
            cached = self._assets.get(r["inst"].instrument_key)
            if cached is None:
                continue
            _, al = P.align(hold_map | {"__c": cached[0].series.pairs})
            R_all = [P.simple_returns(al[a.inst.instrument_key])[-LOOKBACK:] for a in prep.assets]
            rc = P.simple_returns(al["__c"])[-LOOKBACK:]
            S0, _ = P.shrunk_covariance(R_all)
            secs0 = [h.sector for h in holdings]
            w0, _, _ = weights_for(REFERENCE, S0, secs0, [None] * n)
            vol0, dr0 = P.port_vol(w0, S0), P.diversification_ratio(w0, S0)
            add_research = self._research_of(r["inst"].instrument_key)
            add_score = add_research[1] if add_research else None
            for k, h in enumerate(holdings):
                R = [x for j, x in enumerate(R_all) if j != k] + [rc]
                secs = [s for j, s in enumerate(secs0) if j != k] + [r["sector"]]
                S, _ = P.shrunk_covariance(R)
                w, _, _ = weights_for(REFERENCE, S, secs, [None] * n)
                vol1, dr1 = P.port_vol(w, S), P.diversification_ratio(w, S)
                if dr1 <= dr0 + 0.02 or vol1 > vol0 * 1.02:
                    continue
                text = (
                    f"Swapping {h.symbol} for {r['inst'].symbol} keeps {n} holdings and moves "
                    f"estimated volatility {vol0:.1%} to {vol1:.1%}, diversification ratio "
                    f"{dr0:.2f} to {dr1:.2f}."
                )
                if h.research_score is not None and h.research_score < 0:
                    text += (
                        f" {h.symbol} also has a negative research composite "
                        f"({h.research_score:+.2f})."
                    )
                out.append(
                    Replacement(
                        remove=h.symbol,
                        add=r["inst"].symbol,
                        vol_before=vol0,
                        vol_after=vol1,
                        dr_before=dr0,
                        dr_after=dr1,
                        remove_research_score=h.research_score,
                        add_research_score=add_score,
                        explanation=text,
                    )
                )
        out.sort(key=lambda x: (-(x.dr_after - x.dr_before), x.remove, x.add))
        return out[:3]

    def _selection(self, prep: Prepared, pool, series) -> SelectionCheck | None:
        """Bias control: equal-weight your stocks versus random same-size portfolios from the
        candidate universe, over the same sessions, price returns after costs."""
        k = len(prep.assets)
        days = prep.days
        if k < 1 or len(days) <= LOOKBACK + 63:
            return None
        eligible = []
        for inst in pool:
            s = series.get(inst.instrument_key)
            if not isinstance(s, AssetData):
                continue
            m = {t // 86400: c for t, c in s.series.pairs}
            if all(d in m for d in days):
                closes = [m[d] for d in days]
                if P.suspicious_jump(closes) is None:
                    eligible.append(closes)
        if len(eligible) < max(10, 2 * k):
            return None
        rate = (COSTS.buy_rate + COSTS.sell_rate) / 2
        yours = B.equal_weight_cagr(prep.closes, days, LOOKBACK, rate)
        if yours is None:
            return None
        rng = random.Random(2026)
        draws = []
        for _ in range(RANDOM_PORTFOLIOS):
            pick = rng.sample(range(len(eligible)), k)
            c = B.equal_weight_cagr([eligible[i] for i in pick], days, LOOKBACK, rate)
            if c is not None:
                draws.append(c)
        if not draws:
            return None
        draws.sort()
        start = next(i for i in P.month_starts(days) if i - 1 >= LOOKBACK)
        return SelectionCheck(
            portfolios=len(draws),
            size=k,
            universe=f"{len(eligible)} {CANDIDATE_UNIVERSE} stocks with prices over the whole "
            "period",
            start=day_to_date(days[start]),
            end=day_to_date(days[-1]),
            your_cagr=yours,
            median_cagr=statistics.median(draws),
            p10_cagr=draws[int(0.1 * (len(draws) - 1))],
            p90_cagr=draws[int(0.9 * (len(draws) - 1))],
            percentile=B.percentile_of(yours, draws),
            note="Equal weight, monthly rebalanced, price returns after costs, for both your "
            "stocks and the random draws (fixed seed). The universe is today's index, so it "
            "shares the survivorship bias; the comparison isolates stock selection.",
        )

    # --- plans -----------------------------------------------------------------------

    def preferences(self) -> Preferences:
        row = self._db.fetchone("SELECT v FROM meta WHERE k = ?", [PREFS_KEY])
        if row:
            with contextlib.suppress(ValueError):
                return Preferences.model_validate_json(row[0])
        return Preferences()

    def save_preferences(self, prefs: Preferences) -> Preferences:
        self._db.execute(
            "INSERT OR REPLACE INTO meta VALUES (?, ?, ?)",
            [PREFS_KEY, prefs.model_dump_json(), datetime.now(UTC)],
        )
        return prefs

    def holdings_map(self) -> dict[str, tuple[float, float | None]]:
        rows = self._db.fetchall("SELECT instrument_key, quantity, avg_cost FROM holdings")
        return {k: (float(q), float(c) if c is not None else None) for k, q, c in rows}

    async def plan(self, prefs: Preferences) -> PortfolioPlan:
        equities, excluded = self._watch_equities()
        holdings = self.holdings_map()
        drop = {s.upper() for s in prefs.exclude}
        chosen = [i for i in equities if i.symbol.upper() not in drop]
        extra: list[Instrument] = []
        for sym in prefs.include:
            try:
                inst = self._instruments.by_symbol(sym.upper())
            except NotFound:
                excluded.append(Excluded(symbol=sym.upper(), reason="Not an NSE equity symbol."))
                continue
            if all(inst.instrument_key != i.instrument_key for i in chosen + extra):
                extra.append(inst)
        stored = self._stored()
        key = hashlib.sha1(
            json.dumps(
                [
                    prefs.model_dump(mode="json"),
                    [i.instrument_key for i in chosen + extra],
                    sorted(holdings.items()),
                    stored[2].isoformat() if stored else None,
                ]
            ).encode()
        ).hexdigest()
        if key in self._plans:
            self._plans.move_to_end(key)
            return self._plans[key]
        async with self._plan_lock:
            bench, bench_label, _ = await self._benchmark()
            fetched = await self._assets_for(chosen) | await self._assets_for(extra, "added")
            assets: list[AssetData] = []
            for i in chosen + extra:
                a = fetched[i.instrument_key]
                if isinstance(a, str):
                    excluded.append(
                        Excluded(symbol=i.symbol, reason=f"Price history unavailable: {a}")
                    )
                else:
                    assets.append(a)
            prep = planner.prepare(assets, bench)
            prep.excluded = excluded + prep.excluded
            rf, _ = await self._risk_free()
            plan_keys = {a.inst.instrument_key for a in prep.assets}
            others: dict[str, tuple[str, float]] = {}
            for k, (q, _) in holdings.items():
                if q <= 0 or k in plan_keys:
                    continue
                with contextlib.suppress(AppError):
                    inst = self._instruments.get(k)
                    a = await self._asset(inst, divs=False)
                    others[k] = (inst.symbol, a.series.closes[-1])
            prices = await self._data.latest_prices(
                [a.inst for a in prep.assets] + [self._instruments.get(k) for k in others]
            )
            for k, (sym, _) in list(others.items()):
                if k in prices:
                    others[k] = (sym, prices[k][0])
            plan = await asyncio.to_thread(
                planner.build_plan, prep, prefs, rf, holdings, prices, others, bench_label
            )
        self._plans[key] = plan
        while len(self._plans) > PLAN_CACHE:
            self._plans.popitem(last=False)
        return plan

    # --- holdings -----------------------------------------------------------------------

    async def holdings(self) -> list[HoldingOut]:
        rows = self._db.fetchall(
            "SELECT instrument_key, quantity, avg_cost, updated_at FROM holdings "
            "ORDER BY instrument_key"
        )
        found = self._instruments.get_many([r[0] for r in rows])
        insts = [found[r[0]] for r in rows if r[0] in found]
        prices = await self._data.latest_prices(insts) if insts else {}
        out = []
        for k, q, c, at in rows:
            inst = found.get(k)
            if inst is None:
                continue
            px = prices.get(k)
            if px is None:
                with contextlib.suppress(AppError):
                    a = await self._asset(inst, divs=False)
                    px = (a.series.closes[-1], "last close")
            out.append(
                HoldingOut(
                    symbol=inst.symbol,
                    instrument_key=k,
                    name=inst.name,
                    quantity=float(q),
                    avg_cost=float(c) if c is not None else None,
                    price=px[0] if px else None,
                    price_basis=px[1] if px else None,
                    value=float(q) * px[0] if px else None,
                    updated_at=_as_utc(at),
                )
            )
        return out

    def set_holdings(self, items: list[HoldingIn]) -> None:
        resolved = []
        for item in items:
            inst = self._instruments.by_symbol(item.symbol.upper())
            resolved.append((inst.instrument_key, item.quantity, item.avg_cost))
        now = datetime.now(UTC)
        self._db.execute("DELETE FROM holdings")
        for key, qty, cost in resolved:
            if qty > 0:
                self._db.execute(
                    "INSERT OR REPLACE INTO holdings VALUES (?, ?, ?, ?)", [key, qty, cost, now]
                )
        self._plans.clear()
