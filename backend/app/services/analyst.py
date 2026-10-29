"""Portfolio analyst tools: deterministic calculations behind natural questions.

``route`` reads a question without the language model and picks a tool:

- scenario: add, drop, swap or re-weight stocks, or switch objective; compares the plan before
  and after and returns an applicable scenario;
- compare: the four objectives side by side (return, risk, income, diversification,
  concentration);
- investigate: why a stock has done what it did, split into market, sector and stock-specific
  parts, with its weight, risk share, P&L and research changes;
- goal: a target amount and date resampled from the plan's history, plus the monthly amount
  needed for even and three-in-four odds.

Each tool returns facts (for citations and the model) and a plain-English summary that stands
on its own when the model is off, over budget or wrong.
"""

import re
from dataclasses import dataclass, field
from datetime import date

from app.schemas.insights import Fact, Scenario
from app.services.insights import ENGINE, RESEARCH, FactBook, pct

OBJECTIVE_WORDS = {
    "lower_risk": ("lower risk", "low risk", "safer", "less risk", "conservative", "calmer"),
    "balanced": ("balanced",),
    "growth": ("aggressive", "growth", "more return", "higher return"),
    "income": ("income", "dividend"),
}
_UNITS = {
    "crore": 1e7,
    "cr": 1e7,
    "lakh": 1e5,
    "lakhs": 1e5,
    "lac": 1e5,
    "l": 1e5,
    "k": 1e3,
    "thousand": 1e3,
}
_AMOUNT = re.compile(
    r"(?:₹|rs\.?|inr)?\s*(\d[\d,]*(?:\.\d+)?)\s*(crore|cr|lakhs?|lac|l|k|thousand)?\b", re.I
)
_MONTHLY = re.compile(
    r"(?:₹|rs\.?|inr)?\s*(\d[\d,]*(?:\.\d+)?)\s*(crore|cr|lakhs?|lac|l|k|thousand)?\s*"
    r"(?:a|per|every|each|/)\s*month|(?:sip|monthly)\s*(?:of)?\s*(?:₹|rs\.?)?\s*(\d[\d,]*(?:\.\d+)?)\s*"
    r"(crore|cr|lakhs?|lac|l|k|thousand)?",
    re.I,
)


def _value(num: str, unit: str | None) -> float:
    return float(num.replace(",", "")) * _UNITS.get((unit or "").lower(), 1.0)


def parse_monthly(text: str) -> float | None:
    m = _MONTHLY.search(text)
    if not m:
        return None
    if m.group(1):
        return _value(m.group(1), m.group(2))
    return _value(m.group(3), m.group(4))


def parse_years(text: str, today: date) -> int | None:
    m = re.search(r"\bin\s+(\d{1,2})\s*(?:years?|yrs?)\b", text, re.I) or re.search(
        r"\b(\d{1,2})\s*(?:years?|yrs?)\b", text, re.I
    )
    if m:
        return int(m.group(1))
    m = re.search(r"\bby\s+(20\d\d)\b", text)
    if m and int(m.group(1)) > today.year:
        return int(m.group(1)) - today.year
    return None


def parse_target(text: str) -> float | None:
    """The largest rupee amount that is not the monthly contribution or a percentage."""
    monthly = _MONTHLY.search(text)
    cleaned = text[: monthly.start()] + text[monthly.end() :] if monthly else text
    best = None
    for m in _AMOUNT.finditer(cleaned):
        tail = cleaned[m.end() : m.end() + 2]
        if "%" in tail or re.match(r"\s*(years?|yrs?)", cleaned[m.end() : m.end() + 6], re.I):
            continue
        if re.match(r"20\d\d$", m.group(1)) and not m.group(2):
            continue
        v = _value(m.group(1), m.group(2))
        if v >= 10_000 and (best is None or v > best):
            best = v
    return best


def find_symbols(text: str, known: set[str], familiar: set[str] = frozenset()) -> list[str]:
    """NSE symbols in ``text``. Any listed symbol counts when written in capitals; symbols
    already in the user's plan also count in lower case (so "infy" works, but the English word
    "gold" is not read as a ticker)."""
    out = []
    for tok in re.findall(r"[A-Za-z][A-Za-z0-9&-]{1,19}", text):
        up = tok.upper()
        if up in out:
            continue
        if (tok == up and up in known) or up in familiar:
            out.append(up)
    return out


def parse_weights(text: str, symbols: list[str]) -> dict[str, float]:
    out: dict[str, float] = {}
    for sym in symbols:
        s = re.escape(sym)
        m = re.search(rf"(\d{{1,3}}(?:\.\d+)?)\s*%\s*(?:in|of|into|to|on|for)?\s*{s}\b", text, re.I)
        m = m or re.search(
            rf"\b{s}\b\s*(?:were|was|is|at|to|=|weight of|as|becomes)?\s*(\d{{1,3}}(?:\.\d+)?)\s*%",
            text,
            re.I,
        )
        if m:
            v = float(m.group(1)) / 100
            if 0 <= v <= 1:
                out[sym] = v
    return out


def parse_objective(text: str) -> str | None:
    low = text.lower()
    for key, words in OBJECTIVE_WORDS.items():
        if any(w in low for w in words):
            return key
    return None


@dataclass
class Route:
    tool: str  # scenario | compare | investigate | goal | general
    symbols: list[str] = field(default_factory=list)
    add: list[str] = field(default_factory=list)
    remove: list[str] = field(default_factory=list)
    weights: dict[str, float] = field(default_factory=dict)
    objective: str | None = None
    target: float | None = None
    years: int | None = None
    monthly: float | None = None


_REMOVE = re.compile(
    r"\b(drop|remove|sell|exclude|without|exit|get rid of|replace|swap out)\b", re.I
)
_ADD_WORDS = re.compile(r"\b(add|include|buy|bring in)\b", re.I)


def route(
    question: str,
    known: set[str],
    held: set[str],
    today: date,
    familiar: set[str] | None = None,
) -> Route:
    """``held``: symbols already in the plan (watchlist and holdings); ``familiar``: other
    symbols the user has seen (candidates), accepted in lower case."""
    q = question.strip()
    low = q.lower()
    symbols = find_symbols(q, known, held | (familiar or set()))
    weights = parse_weights(q, symbols)
    objective = parse_objective(q)
    if re.search(r"\b(goal|target|retire|reach|corpus|accumulate)\b", low) or (
        parse_target(q) and parse_years(q, today)
    ):
        return Route(
            "goal",
            symbols,
            target=parse_target(q),
            years=parse_years(q, today),
            monthly=parse_monthly(q),
            objective=objective,
        )
    if (
        weights
        or re.search(r"\b(what if|what happens|try|swap|replace|instead)\b", low)
        or (symbols and (_REMOVE.search(low) or re.search(r"\b(add|include|buy)\b", low)))
    ):
        add: list[str] = []
        remove: list[str] = []
        m = re.search(
            r"\b(?:replace|swap)\s+([A-Za-z0-9&-]+)\s+(?:with|for)\s+([A-Za-z0-9&-]+)", q, re.I
        )
        if m and m.group(1).upper() in known and m.group(2).upper() in known:
            remove, add = [m.group(1).upper()], [m.group(2).upper()]
        else:
            for sym in symbols:
                before = low[: low.find(sym.lower())]
                last_remove = max((x.end() for x in _REMOVE.finditer(before)), default=-1)
                last_add = max((x.end() for x in _ADD_WORDS.finditer(before)), default=-1)
                if last_remove > last_add:
                    remove.append(sym)
                elif sym not in held:
                    add.append(sym)
        return Route("scenario", symbols, add, remove, weights, objective)
    if re.search(
        r"\b(compare|comparison|versus|vs\.?|which (objective|strategy|plan)|trade-?offs?"
        r"|best objective)\b",
        low,
    ):
        return Route("compare", symbols, objective=objective)
    if symbols and re.search(
        r"\b(why|underperform\w*|lagging|lag|down|fall\w*|drop\w*|doing|performance|losing"
        r"|loss|weak|investigate|explain)\b",
        low,
    ):
        return Route("investigate", symbols[:1])
    if objective and re.search(r"\b(switch|change|move|use|go)\b", low):
        return Route("scenario", symbols, objective=objective)
    return Route("general", symbols, objective=objective)


@dataclass
class ToolOutcome:
    tool: str
    title: str
    summary: str
    facts: list[Fact]
    data: dict | None = None
    scenario: Scenario | None = None


def metrics(plan) -> dict:
    bt = plan.backtest
    covid = next((s.portfolio for s in plan.stress if s.key == "covid_2020" and s.covered), None)
    return {
        "objective": plan.objective.label,
        "weights": {a.symbol: round(a.weight, 4) for a in plan.assets},
        "volatility": plan.risk.volatility if plan.risk else None,
        "diversification_score": plan.risk.diversification_score if plan.risk else None,
        "largest_weight": plan.risk.largest_weight if plan.risk else None,
        "top_risk_symbol": plan.risk.top_risk_symbol if plan.risk else None,
        "top_risk_share": plan.risk.top_risk_share if plan.risk else None,
        "cagr": bt.pre_tax.cagr if bt else None,
        "after_tax_cagr": bt.after_tax.cagr if bt and bt.after_tax else None,
        "max_drawdown": bt.pre_tax.max_drawdown if bt else None,
        "covid": covid,
        "yield": sum(a.weight * (a.dividend_yield or 0.0) for a in plan.assets),
        "costs": bt.costs_per_year if bt else None,
        "trades": sum(1 for t in plan.trades.lines if t.action != "hold") if plan.trades else 0,
        "charges": plan.trades.est_costs if plan.trades else None,
    }


def scenario_outcome(before, after, scenario: Scenario) -> ToolOutcome:
    book = FactBook()
    a, b = metrics(before), metrics(after)
    wa = ", ".join(f"{k} {pct(v, digits=0)}" for k, v in a["weights"].items())
    wb = ", ".join(f"{k} {pct(v, digits=0)}" for k, v in b["weights"].items())
    book.add(f"Now ({a['objective']}): {wa}.", ENGINE, "estimate")
    book.add(f"Scenario ({b['objective']}): {wb}.", ENGINE, "estimate")
    book.add(
        f"Estimated yearly swings {pct(a['volatility'])} now versus {pct(b['volatility'])} in "
        f"the scenario; diversification score {a['diversification_score']} versus "
        f"{b['diversification_score']}.",
        f"{ENGINE}, trailing-year risk model",
        "estimate",
    )
    if a["cagr"] is not None and b["cagr"] is not None:
        book.add(
            f"Walk-forward backtest: {pct(a['cagr'], True)} a year now versus "
            f"{pct(b['cagr'], True)} in the scenario before tax ({pct(a['after_tax_cagr'], True)} "
            f"versus {pct(b['after_tax_cagr'], True)} after tax); worst fall "
            f"{pct(a['max_drawdown'])} versus {pct(b['max_drawdown'])}.",
            f"{ENGINE}, backtest with stocks picked today",
            "measured",
        )
    if a["covid"] is not None and b["covid"] is not None:
        book.add(
            f"COVID-19 crash replay: {pct(a['covid'], True)} now versus {pct(b['covid'], True)}.",
            ENGINE,
            "replay",
        )
    book.add(
        f"Trailing dividend yield {pct(a['yield'])} now versus {pct(b['yield'])}.",
        ENGINE,
        "measured",
    )
    lines = []
    dv = (b["volatility"] or 0) - (a["volatility"] or 0)
    lines.append(
        f"Estimated swings would go from {pct(a['volatility'])} to {pct(b['volatility'])}"
        f" ({'calmer' if dv < -0.002 else 'more volatile' if dv > 0.002 else 'about the same'})."
    )
    if a["cagr"] is not None and b["cagr"] is not None:
        lines.append(
            f"In the backtest it returned {pct(b['cagr'], True)} a year against "
            f"{pct(a['cagr'], True)} for the current plan, with a worst fall of "
            f"{pct(b['max_drawdown'])} against {pct(a['max_drawdown'])}."
        )
    if b["top_risk_symbol"]:
        lines.append(
            f"{b['top_risk_symbol']} would carry the most risk "
            f"({pct(b['top_risk_share'], digits=0)})."
        )
    lines.append(
        "Past figures use stocks picked today, so treat them as a comparison, not a promise."
    )
    return ToolOutcome(
        "scenario",
        scenario.label or "Scenario",
        " ".join(lines),
        book.facts,
        {"before": a, "after": b},
        scenario,
    )


def compare_outcome(previews, current_key: str) -> ToolOutcome:
    book = FactBook()
    rows = []
    for o in previews:
        book.add(
            f"{o.label}: estimated swings {pct(o.volatility)}, backtest {pct(o.cagr, True)} a year "
            f"({pct(o.after_tax_cagr, True)} after tax), worst fall {pct(o.max_drawdown)}, "
            f"dividend yield {pct(o.dividend_yield)}, diversification score "
            f"{o.diversification_score}, largest weight {o.top_weight_symbol} "
            f"{pct(o.top_weight, digits=0)}.",
            f"{ENGINE}, objective previews",
            "measured",
        )
        rows.append(o.model_dump())
    usable = [o for o in previews if o.volatility is not None]
    if not usable:
        return ToolOutcome(
            "compare",
            "Objectives compared",
            "No objective could be computed yet.",
            book.facts,
            {"rows": rows},
        )

    def best(key, high=True):
        vals = [o for o in usable if getattr(o, key) is not None]
        return (max if high else min)(vals, key=lambda o: getattr(o, key)) if vals else None

    calm, ret, inc, div = (
        best("volatility", False),
        best("cagr"),
        best("dividend_yield"),
        best("diversification_score"),
    )
    parts = []
    if calm:
        parts.append(f"{calm.label} has the smallest estimated swings ({pct(calm.volatility)}).")
    if ret:
        parts.append(
            f"{ret.label} returned the most in the backtest ({pct(ret.cagr, True)} a year)."
        )
    if inc and inc.dividend_yield:
        parts.append(
            f"{inc.label} pays the most income ({pct(inc.dividend_yield)} trailing yield)."
        )
    if div:
        parts.append(f"{div.label} is the most diversified (score {div.diversification_score}).")
    parts.append(
        "No objective wins on everything, and the backtest numbers are flattered by stocks picked "
        "today; choose by the risk you can live with first."
    )
    return ToolOutcome(
        "compare",
        "Objectives compared",
        " ".join(parts),
        book.facts,
        {"rows": rows, "current": current_key},
    )


def investigate_outcome(
    sym: str, perf: dict, holding, plan_asset, research, changes
) -> ToolOutcome:
    """``perf``: {"periods": [(label, stock, sector, market)], "sector_label", "drawdown",
    "vol", "as_of"}."""
    book = FactBook()
    lines = []
    for label, st, sec, mkt in perf["periods"]:
        if st is None:
            continue
        text = f"{sym} {label}: {pct(st, True)}; NIFTY 50 {pct(mkt, True)}"
        if sec is not None:
            text += f"; {perf['sector_label']} {pct(sec, True)}"
        book.add(text + ".", "Upstox daily closes", "measured", perf.get("as_of"))
    main = next(
        (p for p in perf["periods"] if p[0] == "over 1 year" and p[1] is not None), None
    ) or next((p for p in perf["periods"] if p[1] is not None), None)
    if main:
        label, st, sec, mkt = main
        lines.append(
            f"{sym} returned {pct(st, True)} {label} against {pct(mkt, True)} for the NIFTY 50."
        )
        if sec is not None and mkt is not None:
            sector_effect, specific = sec - mkt, st - sec
            book.add(
                f"Split {label}: market {pct(mkt, True)}, sector effect {pct(sector_effect, True)} "
                f"({perf['sector_label']} versus NIFTY 50), stock-specific {pct(specific, True)}.",
                f"{ENGINE}, return attribution",
                "measured",
            )
            driver = (
                "mostly the company itself"
                if abs(specific) > abs(sector_effect)
                else f"mostly its sector ({perf['sector_label']})"
            )
            lines.append(
                f"Of the gap to the market, {pct(sector_effect, True)} came from the sector and "
                f"{pct(specific, True)} was specific to {sym}, so the move was {driver}."
            )
    if perf.get("drawdown") is not None:
        book.add(
            f"{sym} is {pct(perf['drawdown'])} below its 1-year high.",
            "Upstox daily closes",
            "measured",
        )
        lines.append(f"It is {pct(abs(perf['drawdown']))} below its high of the past year.")
    if holding is not None and holding.pnl is not None:
        book.add(
            f"Your {holding.quantity:g} shares: invested Rs {holding.invested:,.0f}, now Rs "
            f"{holding.value:,.0f}, P&L {pct(holding.pnl_pct, True)}.",
            "Your holdings",
            "observed",
        )
        lines.append(f"Your position is {pct(holding.pnl_pct, True)} on cost.")
    if plan_asset is not None:
        book.add(
            f"In the current plan {sym} has weight {pct(plan_asset.weight)} and risk share "
            f"{pct(plan_asset.risk_share)}; volatility {pct(plan_asset.volatility)}.",
            ENGINE,
            "estimate",
        )
    if research is not None:
        c = research.composite
        weakest = sorted(
            (a for a in research.agents if a.score is not None), key=lambda a: a.score or 0
        )
        text = (
            f"{sym} research composite {c.score:+.2f} ({c.signal})"
            if c.score is not None
            else f"{sym} research: {c.signal}"
        )
        if weakest:
            text += f"; weakest agent {weakest[0].agent} {weakest[0].score:+.2f}"
        book.add(text + ".", RESEARCH, "observed", research.computed_at)
        if weakest and (weakest[0].score or 0) < 0 and weakest[0].rationale:
            lines.append(f"Research's weakest view: {weakest[0].rationale}")
    if changes is not None and changes.items:
        book.add(f"{sym} research changes: {changes.summary}", RESEARCH, "observed", changes.until)
    lines.append(
        "Past moves explain what happened; they do not tell you what happens next, and the "
        "research scores have not been shown to predict returns."
    )
    return ToolOutcome(
        "investigate",
        f"Why {sym} did what it did",
        " ".join(lines),
        book.facts,
        perf | {"symbol": sym},
    )


def goal_outcome(proj, needed: dict[str, float | None], route_: Route) -> ToolOutcome:
    book = FactBook()
    book.add(
        f"Target Rs {proj.target:,.0f} in {proj.years} years from Rs {proj.initial:,.0f} plus "
        f"Rs {proj.monthly:,.0f} a month: reached in {pct(proj.probability, digits=0)} of "
        f"resampled histories; middle outcome Rs {proj.p50:,.0f}, weak case Rs {proj.p10:,.0f}.",
        f"{ENGINE}, block bootstrap of the plan's after-tax months",
        "estimate",
    )
    if proj.benchmark_probability is not None:
        book.add(
            f"The same calculation on the NIFTY 50 reaches the target in "
            f"{pct(proj.benchmark_probability, digits=0)} of histories.",
            ENGINE,
            "estimate",
        )
    for label, v in needed.items():
        if v == 0:
            book.add(f"No monthly additions are needed for {label} odds.", ENGINE, "estimate")
        elif v is not None:
            book.add(f"Monthly amount for {label} odds: about Rs {v:,.0f}.", ENGINE, "estimate")
        else:
            book.add(
                f"{label.capitalize()} odds are out of reach within twice the straight-line "
                "monthly amount.",
                ENGINE,
                "estimate",
            )
    parts = [
        f"In {pct(proj.probability, digits=0)} of resampled histories the plan reached "
        f"Rs {proj.target:,.0f} in {proj.years} years (middle outcome Rs {proj.p50:,.0f})."
    ]
    if needed.get("three-in-four") == 0:
        parts.append("Even without monthly additions the odds were about three in four or better.")
    elif needed.get("three-in-four") is not None:
        parts.append(
            "For roughly three-in-four odds you would add about "
            f"Rs {needed['three-in-four']:,.0f} a month."
        )
    parts.append(
        "This is a hypothesis from one stretch of history with stocks picked today, not a forecast."
    )
    return ToolOutcome(
        "goal",
        "Goal check",
        " ".join(parts),
        book.facts,
        proj.model_dump(mode="json") | {"needed": needed},
    )
