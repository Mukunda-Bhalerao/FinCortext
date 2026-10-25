"""Deterministic insights: what matters in the portfolio, why, and what the user could do.

Each insight cites numbered facts, and each fact names its source and whether it is measured
(a backtest on real data), an estimate (trailing-year risk model), a replay (today's weights
through a past episode) or observed (a stored research reading). The language model, when
enabled, only rephrases these facts.
"""

from datetime import UTC, datetime, timedelta

from app.schemas.insights import Fact, Insight, InsightAction
from app.schemas.plan import PortfolioPlan
from app.schemas.portfolio import PortfolioAnalysis
from app.schemas.research import ResearchItem
from app.tools.research_diff import AGENT_LABEL, SIGNAL_LABEL

ENGINE = "FinCortext portfolio engine"
RESEARCH = "FinCortext research agents"
STALE_RESEARCH = timedelta(hours=24)


def pct(x: float | None, signed: bool = False, digits: int = 1) -> str:
    if x is None:
        return "n/a"
    s = f"{abs(x) * 100:.{digits}f}%"
    if signed:
        return ("+" if x > 0 else "-" if x < 0 else "") + s
    return ("-" if x < 0 else "") + s


class FactBook:
    def __init__(self) -> None:
        self.facts: list[Fact] = []

    def add(self, text: str, source: str, basis: str, as_of: datetime | None = None) -> str:
        fid = f"F{len(self.facts) + 1}"
        self.facts.append(Fact(id=fid, text=text, source=source, basis=basis, as_of=as_of))  # type: ignore[arg-type]
        return fid


def _when(d) -> datetime | None:
    return datetime(d.year, d.month, d.day, tzinfo=UTC) if d else None


def build(
    analysis: PortfolioAnalysis | None,
    plan: PortfolioPlan | None,
    research: list[ResearchItem],
    now: datetime | None = None,
) -> tuple[str, list[Insight], list[Fact]]:
    """Returns (headline, insights ordered by importance, facts)."""
    now = now or datetime.now(UTC)
    book = FactBook()
    out: list[Insight] = []
    if plan is None or not plan.assets:
        n = len(plan.assets) if plan else 0
        excluded = plan.excluded if plan else []
        for e in excluded:
            out.append(
                Insight(
                    id=f"excluded-{e.symbol}",
                    kind="data",
                    severity="medium",
                    title=f"{e.symbol} is left out",
                    body=e.reason,
                    facts=[book.add(f"{e.symbol} excluded: {e.reason}", ENGINE, "observed")],
                )
            )
        headline = (
            "Add at least two stocks to your watchlist to build a portfolio."
            if n == 0
            else "Add another stock to compare portfolios."
        )
        return headline, out, book.facts

    risk = plan.risk
    bt = plan.backtest
    obj = plan.objective.label
    asof = _when(plan.as_of)
    n = len(plan.assets)
    weights = ", ".join(f"{a.symbol} {pct(a.weight, digits=0)}" for a in plan.assets)
    f_weights = book.add(
        f"{obj} weights: {weights}.", f"{ENGINE}, {plan.objective.method}", "estimate", asof
    )

    # --- performance (measured) -----------------------------------------------------
    perf_phrase = None
    if bt:
        p, b = bt.pre_tax, bt.benchmark
        f_perf = book.add(
            f"From {bt.start:%b %Y} to {bt.end:%b %Y} ({bt.years:.1f} years) the {obj} plan "
            f"returned {pct(p.cagr, True)} a year after trading costs, versus "
            f"{pct(b.cagr, True)} for {bt.benchmark_label}.",
            f"{ENGINE}, walk-forward backtest on Upstox prices and Yahoo Finance dividends",
            "measured",
            _when(bt.end),
        )
        facts = [f_perf]
        if bt.after_tax and bt.after_tax.cagr is not None:
            facts.append(
                book.add(
                    f"After estimated capital gains and dividend tax the plan returned "
                    f"{pct(bt.after_tax.cagr, True)} a year.",
                    f"{ENGINE}, Indian tax rules for listed equity",
                    "measured",
                    _when(bt.end),
                )
            )
        f_dd = book.add(
            f"Its worst fall from a peak was {pct(p.max_drawdown)}, versus "
            f"{pct(b.max_drawdown)} for {bt.benchmark_label}.",
            ENGINE,
            "measured",
            _when(bt.end),
        )
        facts.append(f_dd)
        gap = (p.cagr or 0) - (b.cagr or 0)
        luck = ""
        if bt.uncertainty:
            u = bt.uncertainty
            facts.append(
                book.add(
                    f"Resampling the daily history puts the yearly gap to the benchmark between "
                    f"{pct(u.excess_low, True)} and {pct(u.excess_high, True)} (90% range); the "
                    f"plan came out ahead in {pct(u.prob_outperform, digits=0)} of resamples.",
                    f"{ENGINE}, {u.method}",
                    "measured",
                )
            )
            if u.excess_low < 0 < u.excess_high:
                luck = " The gap is within what luck alone could produce."
        if gap < -0.01:
            perf_phrase = f"has trailed the {bt.benchmark_label.split(' (')[0]}"
            title = f"Trailed the market by {pct(-gap)} a year"
            sev = "medium"
        elif gap > 0.01:
            perf_phrase = f"has beaten the {bt.benchmark_label.split(' (')[0]}"
            title = f"Ahead of the market by {pct(gap)} a year"
            sev = "low"
        else:
            perf_phrase = f"has kept pace with the {bt.benchmark_label.split(' (')[0]}"
            title = "Kept pace with the market"
            sev = "low"
        if analysis and analysis.selection:
            s = analysis.selection
            facts.append(
                book.add(
                    f"Your {s.size} stocks, equally weighted, returned {pct(s.your_cagr, True)} a "
                    f"year from {s.start:%b %Y} to {s.end:%b %Y}, better than "
                    f"{pct(s.percentile, digits=0)} of {s.portfolios} random {s.size}-stock "
                    f"portfolios from the same index (median {pct(s.median_cagr, True)}).",
                    f"{ENGINE}, selection check, {s.universe}",
                    "measured",
                )
            )
            if 0.25 <= s.percentile <= 0.75:
                luck += (
                    f" Random {s.size}-stock portfolios from today's index did about as well "
                    f"(median {pct(s.median_cagr, True)} a year), so the lead says more about "
                    "hindsight on today's index than about these picks."
                    if gap > 0.01
                    else ""
                )
        out.append(
            Insight(
                id="performance",
                kind="performance",
                severity=sev,  # type: ignore[arg-type]
                title=title,
                body=f"Over {bt.years:.1f} years this mix returned {pct(p.cagr, True)} a year "
                f"against {pct(b.cagr, True)}, with a worst fall of {pct(p.max_drawdown)}.{luck} "
                "Past results are not a forecast.",
                facts=facts,
            )
        )

    # --- concentration (estimate) ------------------------------------------------------
    if risk and n >= 2:
        f_risk = book.add(
            f"Estimated yearly volatility is {pct(risk.volatility)} ({risk.level_text}); "
            f"{risk.top_risk_symbol} carries {pct(risk.top_risk_share, digits=0)} of the "
            "portfolio's risk.",
            f"{ENGINE}, trailing 252-session covariance with shrinkage",
            "estimate",
            asof,
        )
        if risk.top_risk_share >= 0.45:
            out.append(
                Insight(
                    id="concentration",
                    kind="risk",
                    severity="high" if risk.top_risk_share >= 0.6 else "medium",
                    title=f"{risk.top_risk_symbol} drives {pct(risk.top_risk_share, digits=0)} "
                    "of your risk",
                    body=f"A bad stretch for {risk.top_risk_symbol} would move the whole "
                    "portfolio. Spreading money across stocks that move differently lowers this.",
                    facts=[f_risk, f_weights],
                    action=InsightAction(
                        kind="objective", label="Try Lower risk", objective="lower_risk"
                    )
                    if plan.preferences.objective != "lower_risk"
                    else None,
                )
            )
        top_sector, top_sw = max(risk.sector_weights.items(), key=lambda kv: kv[1])
        if top_sw >= 0.5 and len(risk.sector_weights) >= 1:
            f_sec = book.add(
                f"{pct(top_sw, digits=0)} of the plan is in {top_sector}.",
                f"{ENGINE}, NSE industry classification",
                "estimate",
                asof,
            )
            out.append(
                Insight(
                    id="sector",
                    kind="risk",
                    severity="medium",
                    title=f"{pct(top_sw, digits=0)} in one sector",
                    body=f"{top_sector} news, regulation or demand affects most of your money at "
                    "once.",
                    facts=[f_sec],
                )
            )
        if n <= 3:
            out.append(
                Insight(
                    id="few-stocks",
                    kind="risk",
                    severity="medium",
                    title=f"Only {n} stocks",
                    body="With so few stocks, one company's results can swing the whole "
                    "portfolio, and the weighting methods barely differ.",
                    facts=[f_weights],
                )
            )

    if analysis and analysis.correlation and n >= 2:
        c = analysis.correlation
        pairs = [
            (c.symbols[i], c.symbols[j], c.matrix[i][j])
            for i in range(len(c.symbols))
            for j in range(i + 1, len(c.symbols))
            if c.matrix[i][j] >= 0.65
        ]
        if pairs:
            a, b_, v = max(pairs, key=lambda x: x[2])
            f_corr = book.add(
                f"{a} and {b_} had a daily-return correlation of {v:.2f} over the last year.",
                ENGINE,
                "estimate",
                _when(analysis.as_of),
            )
            out.append(
                Insight(
                    id="correlation",
                    kind="risk",
                    severity="medium",
                    title=f"{a} and {b_} move together",
                    body="Owning both adds little protection: they tend to rise and fall on the "
                    "same days.",
                    facts=[f_corr],
                )
            )

    # --- stress replay -----------------------------------------------------------------
    covered = [s for s in plan.stress if s.covered and s.portfolio is not None]
    if covered:
        worst = min(covered, key=lambda s: s.portfolio or 0)
        f_st = book.add(
            f"With today's weights, the {worst.name.lower()} ({worst.start:%d %b %Y} to "
            f"{worst.end:%d %b %Y}) would have taken the portfolio {pct(worst.portfolio, True)} "
            f"versus {pct(worst.benchmark, True)} for the NIFTY 50.",
            f"{ENGINE}, replay on historical total returns",
            "replay",
        )
        out.append(
            Insight(
                id="stress",
                kind="risk",
                severity="medium"
                if (worst.portfolio or 0) < (worst.benchmark or 0) - 0.03
                else "low",
                title=f"{worst.name}: {pct(worst.portfolio, True)}",
                body=f"Replaying today's mix through that episode it would have moved "
                f"{pct(worst.portfolio, True)} while the NIFTY 50 moved "
                f"{pct(worst.benchmark, True)}. A guide to how it behaves in a sell-off, not a "
                "prediction.",
                facts=[f_st],
            )
        )

    # --- opportunities -------------------------------------------------------------------
    opp_phrase = None
    if analysis and analysis.candidates:
        held = {a.symbol for a in plan.assets}
        best = next(
            (
                c
                for c in analysis.candidates
                if c.symbol not in held
                and c.validation
                and c.validation.vol_with is not None
                and c.validation.vol_without is not None
                and c.validation.vol_with < c.validation.vol_without
            ),
            None,
        )
        if best and best.validation:
            v = best.validation
            f_c = book.add(
                f"Adding {best.symbol} ({best.sector}) at about "
                f"{pct(best.weight_if_added, digits=0)} "
                f"lowers estimated volatility from {pct(best.vol_before)} to "
                f"{pct(best.vol_after)}; its average correlation with your stocks is "
                f"{best.avg_correlation:.2f}.",
                f"{ENGINE}, {analysis.candidate_universe} screen, trailing year",
                "estimate",
                _when(analysis.as_of),
            )
            f_v = book.add(
                f"In the earlier, unseen period {v.start:%b %Y} to {v.end:%b %Y}, adding "
                f"{best.symbol} lowered measured volatility from {pct(v.vol_without)} to "
                f"{pct(v.vol_with)} and the worst fall from {pct(v.mdd_without)} to "
                f"{pct(v.mdd_with)}.",
                f"{ENGINE}, out-of-sample walk-forward",
                "measured",
            )
            opp_phrase = f"adding {best.symbol} would diversify it most"
            out.append(
                Insight(
                    id=f"add-{best.symbol}",
                    kind="opportunity",
                    severity="medium",
                    title=f"{best.symbol} would steady the mix",
                    body=f"{best.symbol} ({best.sector}) tends to move differently from your "
                    f"stocks. It cut swings in the screening year and in an earlier period the "
                    "screen never saw.",
                    facts=[f_c, f_v],
                    action=InsightAction(
                        kind="add", label=f"Try adding {best.symbol}", symbol=best.symbol
                    ),
                )
            )
        for r in analysis.replacements[:1]:
            if r.remove in held and r.add not in held:
                f_r = book.add(r.explanation, f"{ENGINE}, trailing year", "estimate")
                out.append(
                    Insight(
                        id=f"swap-{r.remove}-{r.add}",
                        kind="opportunity",
                        severity="low",
                        title=f"Swap {r.remove} for {r.add}?",
                        body=f"Keeps the same number of stocks and lowers estimated swings from "
                        f"{pct(r.vol_before)} to {pct(r.vol_after)}.",
                        facts=[f_r],
                        action=InsightAction(
                            kind="remove", label=f"Try without {r.remove}", symbol=r.remove
                        ),
                    )
                )

    if analysis and analysis.objectives:
        current = next(
            (o for o in analysis.objectives if o.key == plan.preferences.objective), None
        )
        calm = next((o for o in analysis.objectives if o.key == "lower_risk"), None)
        if (
            current
            and calm
            and current.key != "lower_risk"
            and current.volatility
            and calm.volatility
            and calm.volatility < current.volatility * 0.9
        ):
            f_o = book.add(
                f"Lower risk weights: estimated volatility {pct(calm.volatility)} versus "
                f"{pct(current.volatility)} for {current.label}; measured return "
                f"{pct(calm.cagr, True)} versus {pct(current.cagr, True)} a year.",
                ENGINE,
                "measured",
            )
            out.append(
                Insight(
                    id="objective-lower-risk",
                    kind="opportunity",
                    severity="low",
                    title="A calmer mix of the same stocks",
                    body=f"Re-weighting toward steadier stocks cuts estimated swings from "
                    f"{pct(current.volatility)} to {pct(calm.volatility)}; in the backtest it "
                    f"returned {pct(calm.cagr, True)} a year versus {pct(current.cagr, True)}.",
                    facts=[f_o],
                    action=InsightAction(
                        kind="objective", label="Compare Lower risk", objective="lower_risk"
                    ),
                )
            )

    if (
        analysis
        and analysis.selection
        and (analysis.selection.percentile < 0.25 or analysis.selection.percentile > 0.75)
    ):
        s = analysis.selection
        f_s = book.add(
            f"Your {s.size} stocks, equally weighted, returned {pct(s.your_cagr, True)} a year "
            f"from {s.start:%b %Y} to {s.end:%b %Y}, beating {pct(s.percentile, digits=0)} of "
            f"{s.portfolios} random {s.size}-stock portfolios (median {pct(s.median_cagr, True)}).",
            f"{ENGINE}, selection check, {s.universe}",
            "measured",
        )
        if s.percentile < 0.25 or s.percentile > 0.75:
            good = s.percentile > 0.75
            out.append(
                Insight(
                    id="selection",
                    kind="performance",
                    severity="low" if good else "medium",
                    title=f"Your picks beat {pct(s.percentile, digits=0)} of random portfolios",
                    body=(
                        "Your stock choices did better than most random picks from the same "
                        "index, though past winners often cool off."
                        if good
                        else "Random picks from the same index usually did better than this "
                        "selection over the same years."
                    ),
                    facts=[f_s],
                )
            )

    # --- research readings and changes (observed) ----------------------------------------
    for item in research:
        rep = item.report
        if rep is None:
            continue
        sym = item.instrument.symbol
        ch = item.changes
        if ch and any(c.kind == "signal" for c in ch.items):
            first = next(c for c in ch.items if c.kind == "signal")
            f_ch = book.add(
                f"{sym}: {first.text} Compared with the report from {ch.since:%d %b %H:%M} UTC.",
                RESEARCH,
                "observed",
                ch.until,
            )
            now_signal = (
                rep.composite.signal
                if first.agent == "composite"
                else next((a.signal for a in rep.agents if a.agent == first.agent), "neutral")
            )
            out.append(
                Insight(
                    id=f"change-{sym}",
                    kind="change",
                    severity="medium" if first.direction == "worse" else "low",
                    title=f"{sym}: {AGENT_LABEL[first.agent].lower()} view now "
                    f"{SIGNAL_LABEL[now_signal]}",
                    body=ch.summary,
                    facts=[f_ch],
                    action=InsightAction(kind="open_stock", label=f"Open {sym}", symbol=sym),
                )
            )
        c = rep.composite
        if c.signal == "negative" and c.confidence >= 0.4:
            f_n = book.add(
                f"{sym} research composite is {c.score:+.2f} (negative) with confidence "
                f"{pct(c.confidence, digits=0)}, from {c.agents_used} of 4 agents.",
                RESEARCH,
                "observed",
                rep.computed_at,
            )
            weak = sorted(
                (a for a in rep.agents if a.score is not None and a.score < 0),
                key=lambda a: a.score or 0,
            )
            reason = (
                f" Weakest: {AGENT_LABEL[weak[0].agent].lower()} ({weak[0].score:+.2f})."
                if weak
                else ""
            )
            out.append(
                Insight(
                    id=f"negative-{sym}",
                    kind="risk",
                    severity="medium",
                    title=f"Research leans negative on {sym}",
                    body=f"The four research agents score {sym} at {c.score:+.2f}.{reason} "
                    "Read the evidence before acting; scores summarise data, they do not predict "
                    "prices.",
                    facts=[f_n],
                    action=InsightAction(
                        kind="open_stock", label=f"See {sym} evidence", symbol=sym
                    ),
                )
            )
        if now - rep.computed_at > STALE_RESEARCH:
            out.append(
                Insight(
                    id=f"stale-{sym}",
                    kind="data",
                    severity="low",
                    title=f"{sym} research is {(now - rep.computed_at) // timedelta(hours=1)} "
                    "hours old",
                    body="It refreshes automatically every six hours while the app runs.",
                    facts=[
                        book.add(
                            f"{sym} research computed {rep.computed_at:%d %b %H:%M} UTC.",
                            RESEARCH,
                            "observed",
                            rep.computed_at,
                        )
                    ],
                    action=InsightAction(kind="research", label="Refresh research", symbol=sym),
                )
            )

    for e in plan.excluded:
        out.append(
            Insight(
                id=f"excluded-{e.symbol}",
                kind="data",
                severity="low",
                title=f"{e.symbol} is left out",
                body=e.reason,
                facts=[book.add(f"{e.symbol} excluded: {e.reason}", ENGINE, "observed")],
            )
        )

    order = {"high": 0, "medium": 1, "low": 2}
    kind_order = {"risk": 0, "performance": 1, "opportunity": 2, "change": 3, "data": 4}
    out.sort(key=lambda i: (order[i.severity], kind_order[i.kind]))

    size = f"{n}-stock " if n > 1 else ""
    level = f"is {risk.level_text}" if risk and risk.level_text else "has been analysed"
    parts = [f"Your {size}portfolio {level}"]
    if perf_phrase:
        parts.append(perf_phrase)
    headline = " and ".join(parts)
    headline += f"; {opp_phrase}." if opp_phrase else "."
    return headline, out, book.facts


def plan_facts(book: FactBook, plan: PortfolioPlan) -> None:
    """Detail facts for the assistant beyond the insights: per-stock data, years, stress."""
    asof = _when(plan.as_of)
    for a in plan.assets:
        parts = [
            f"{a.symbol} ({a.sector}): weight {pct(a.weight)}, risk share {pct(a.risk_share)}, "
            f"volatility {pct(a.volatility)}"
        ]
        if a.momentum is not None:
            parts.append(f"12-1 month return {pct(a.momentum, True)}")
        if a.dividend_yield is not None:
            parts.append(f"trailing dividend yield {pct(a.dividend_yield)}")
        if a.research_score is not None:
            parts.append(f"research composite {a.research_score:+.2f}")
        book.add("; ".join(parts) + ".", ENGINE, "estimate", asof)
    bt = plan.backtest
    if bt:
        for y in bt.years_table:
            book.add(
                f"{y.year}{' (partial)' if y.partial else ''}: plan {pct(y.portfolio, True)}, "
                f"{bt.benchmark_label} {pct(y.benchmark, True)}.",
                ENGINE,
                "measured",
            )
        book.add(
            f"Trading costs averaged {pct(bt.costs_per_year, digits=2)} a year with "
            f"{pct(bt.turnover_per_year, digits=0)} yearly turnover; dividends added "
            f"{pct(bt.dividends_per_year)} a year"
            + (
                f"; taxes took {pct(bt.taxes_per_year)} a year."
                if bt.taxes_per_year is not None
                else "."
            ),
            ENGINE,
            "measured",
        )
    for s in plan.stress:
        if s.covered:
            book.add(
                f"{s.name} ({s.start:%d %b %Y} to {s.end:%d %b %Y}): plan "
                f"{pct(s.portfolio, True)}, "
                f"NIFTY 50 {pct(s.benchmark, True)}.",
                ENGINE,
                "replay",
            )
    if plan.current:
        c = plan.current
        book.add(
            f"{c.label}: estimated volatility {pct(c.volatility)}"
            + (f", measured return {pct(c.cagr, True)} a year" if c.cagr is not None else "")
            + ".",
            ENGINE,
            "measured" if c.cagr is not None else "estimate",
        )
    if plan.trades:
        t = plan.trades
        moves = [f"{x.action} {abs(x.delta_qty)} {x.symbol}" for x in t.lines if x.action != "hold"]
        if moves:
            book.add(
                f"To reach the plan from {'your holdings' if t.basis == 'holdings' else 'cash'}: "
                f"{', '.join(moves)}; estimated charges Rs {t.est_costs:,.0f}.",
                ENGINE,
                "estimate",
            )
    for line in plan.explanation:
        book.add(line, ENGINE, "estimate", asof)
