"""Macro analyst: market-wide regime plus the company's sector exposure to macro drivers.

Market regime (weight 0.5) scores rates, currency, crude, global yields, inflation and
equity risk appetite. Sector exposure (weight 0.5) applies the sensitivity table below to the
same driver moves. The table is an editorial rule set, versioned with the method, and is
shown with every output.
"""

from app.agents.base import AgentBuilder, ResearchContext, fmt_value, pct, r2
from app.schemas.research import AgentOutput, MacroIndicator
from app.tools import technicals as ta
from app.tools.scoring import scale

METHOD = "macro-v1"
RULES_SOURCE = "FinCortext sector sensitivity rules v1"

# Market regime: indicator key -> change that maps to (-1, +1) as a driver move. A rising
# driver is scored as negative for the broad Indian equity market.
REGIME = {
    "in10y": (-0.5, 0.5),  # pp change; rising yields weigh on equities
    "usdinr": (-4.0, 4.0),  # % change; rupee weakness weighs (FPI outflows)
    "brent": (-25.0, 25.0),  # % change; India is a net crude importer
    "us10y": (-0.75, 0.75),  # pp change; tighter global liquidity
}

# Driver direction: +1 when the driver rises (yields up, rupee weaker, crude up).
# Coefficient: how a sector's earnings typically respond to that rise.
SENSITIVITY: dict[str, dict[str, float]] = {
    "Financial Services": {"in10y": -1.0},
    "Realty": {"in10y": -1.0},
    "Automobile and Auto Components": {"in10y": -0.5, "brent": -0.5},
    "Information Technology": {"usdinr": 1.0},
    "Healthcare": {"usdinr": 0.5},
    "Fast Moving Consumer Goods": {"brent": -0.5},
    "Chemicals": {"brent": -0.5, "usdinr": 0.3},
    "Consumer Durables": {"brent": -0.3, "in10y": -0.3},
    "Capital Goods": {"in10y": -0.5},
    "Construction": {"in10y": -0.5},
    "Construction Materials": {"brent": -0.5, "in10y": -0.3},
    "Metals & Mining": {"usdinr": 0.3},
    "Power": {"in10y": -0.5},
    "Telecommunication": {"in10y": -0.3},
    "Textiles": {"usdinr": 0.5},
    "Consumer Services": {"in10y": -0.3},
    "Oil Gas & Consumable Fuels": {},  # refiners and producers respond in opposite directions
}
DRIVER_LABEL = {"in10y": "India 10Y yield", "usdinr": "USD/INR", "brent": "Brent crude"}


def driver_move(ind: MacroIndicator) -> float | None:
    """Driver move normalised to -1..1 (+1 = strongly rising)."""
    lo, hi = REGIME[ind.key]
    if ind.change is None or ind.stale:
        return None
    return scale(ind.change, lo, hi)


def run(ctx: ResearchContext) -> AgentOutput:
    b = AgentBuilder("macro", ctx.instrument.symbol, METHOD, ctx.now)
    regime = b.factor("Market regime", 0.5)
    exposure = b.factor("Sector exposure", 0.5)
    by_key = {m.key: m for m in ctx.macro}
    if not ctx.macro:
        b.gap(f"Macro series unavailable: {ctx.problems.get('macro', 'no data')}.")

    for key in REGIME:
        ind = by_key.get(key)
        if ind is None:
            continue
        move = driver_move(ind)
        b.evidence(
            "Market regime",
            f"{ind.label} change ({ind.change_window})",
            r2(ind.change),
            unit=ind.change_unit,
            detail=f"level {fmt_value(r2(ind.value), ind.unit)}",
            source=ind.source,
            as_of=ind.as_of,
            score=regime.add(-move) if move is not None else None,
        )
        if ind.stale or ind.problem:
            b.gap(f"{ind.label}: {ind.problem or 'latest observation is too old to score'}.")

    cpi = by_key.get("incpi")
    if cpi is not None and cpi.value is not None and not cpi.stale:
        b.evidence(
            "Market regime",
            "India CPI inflation (YoY)",
            r2(cpi.value),
            unit="%",
            detail="vs RBI target 4%",
            source=cpi.source,
            as_of=cpi.as_of,
            score=regime.add(scale(cpi.value, 7.0, 1.0)),
        )
    elif cpi is not None:
        b.gap(f"{cpi.label}: {cpi.problem or 'latest observation is too old to score'}.")

    _market_risk(b, ctx, regime)
    _exposure(b, ctx, exposure, by_key)
    b.gap("Policy and global events: no structured event calendar is connected; not scored.")
    return b.build(quality=0.8)  # rule-based sector mapping: confidence is capped


def _market_risk(b: AgentBuilder, ctx: ResearchContext, regime) -> None:
    n = ctx.benchmark
    if n is not None and (sma200 := ta.sma(n.closes, 200)):
        dist = n.closes[-1] / sma200 - 1
        b.evidence(
            "Market regime",
            "NIFTY 50 vs 200-day average",
            pct(dist),
            unit="%",
            source=n.source,
            as_of=n.as_of,
            score=regime.add(scale(dist, -0.08, 0.08)),
        )
    else:
        b.gap("NIFTY 50 trend: daily index prices unavailable.")
    v = ctx.vix
    if v is not None and v.closes:
        b.evidence(
            "Market regime",
            "India VIX",
            r2(v.closes[-1]),
            detail="long-run typical range 12-20",
            source=v.source,
            as_of=v.as_of,
            score=regime.add(scale(v.closes[-1], 23.0, 7.0)),
        )
    else:
        b.gap("India VIX: daily index prices unavailable.")


def _exposure(b: AgentBuilder, ctx: ResearchContext, exposure, by_key) -> None:
    if not ctx.industry:
        b.gap("Sector exposure: industry classification unavailable.")
        return
    rules = SENSITIVITY.get(ctx.industry)
    if rules is None:
        b.gap(f"Sector exposure: no sensitivity rule for {ctx.industry}.")
        return
    if not rules:
        exposure.weight = 0.0
        exposure.note = "Mixed sensitivities within this industry; not scored"
        b.evidence(
            "Sector exposure",
            "Rule",
            "Mixed: refiners and producers respond in opposite directions",
            source=RULES_SOURCE,
        )
        return
    total, weight = 0.0, 0.0
    for key, coef in rules.items():
        ind = by_key.get(key)
        move = driver_move(ind) if ind else None
        direction = "benefits from" if coef > 0 else "is hurt by"
        b.evidence(
            "Sector exposure",
            f"{DRIVER_LABEL[key]} sensitivity",
            coef,
            detail=f"{ctx.industry} {direction} a rising {DRIVER_LABEL[key]}",
            source=RULES_SOURCE,
            score=coef * move if move is not None else None,
        )
        if move is not None:
            total += coef * move
            weight += abs(coef)
    if weight:
        exposure.add(max(-1.0, min(1.0, total / weight)))
