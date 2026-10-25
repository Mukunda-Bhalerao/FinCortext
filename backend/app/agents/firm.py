"""Firm analyst: valuation, profitability, growth, balance sheet and price technicals.

Factor weights: valuation 0.25, profitability 0.20, growth 0.20, balance sheet 0.10,
technicals 0.25. Valuation and margins are compared with the median of the peer set.
"""

from app.agents.base import AgentBuilder, ResearchContext, fmt_value, pct, r2
from app.providers import yahoo
from app.schemas.research import AgentOutput
from app.tools import technicals as ta
from app.tools.scoring import median, scale

METHOD = "firm-v1"
LENDERS = {"Financial Services"}  # debt/equity is not a meaningful leverage measure for lenders


def run(ctx: ResearchContext) -> AgentOutput:
    b = AgentBuilder("firm", ctx.instrument.symbol, METHOD, ctx.now)
    _fundamentals(b, ctx)
    _technicals(b, ctx)
    b.gap("ESG: no free ESG rating source covers NSE companies; not scored.")
    f = ctx.fundamentals
    if f is not None and f.esg_total is not None:
        b.evidence("ESG", "Sustainalytics ESG risk", r2(f.esg_total), source=yahoo.SOURCE)
    return b.build()


def _fundamentals(b: AgentBuilder, ctx: ResearchContext) -> None:
    valuation = b.factor("Valuation", 0.25)
    profitability = b.factor("Profitability", 0.20)
    growth = b.factor("Growth", 0.20)
    balance = b.factor("Balance sheet", 0.10)
    f = ctx.fundamentals
    if f is None:
        b.gap(f"Fundamentals unavailable: {ctx.problems.get('fundamentals', 'no data')}")
        return
    src, at = yahoo.SOURCE, f.fetched_at
    peers = [p.fundamentals for p in ctx.peers if p.fundamentals is not None]
    peer_note = f"{len(peers)} peers" if peers else None

    def peer_median(attr: str) -> float | None:
        vals = [getattr(p, attr) for p in peers]
        return median([v for v in vals if v is not None and v > 0]) if len(peers) >= 3 else None

    # Valuation: discount or premium to the peer median multiple.
    if f.trailing_eps is not None and f.trailing_eps <= 0:
        s = valuation.add(-0.5)
        b.evidence(
            "Valuation",
            "Trailing EPS",
            r2(f.trailing_eps),
            unit="INR",
            detail="Loss-making on a trailing basis; P/E not meaningful",
            source=src,
            as_of=at,
            score=s,
        )
    elif f.trailing_pe is not None:
        med = peer_median("trailing_pe")
        s = valuation.add(scale(1 - f.trailing_pe / med, -0.5, 0.5)) if med else None
        b.evidence(
            "Valuation",
            "P/E (trailing)",
            r2(f.trailing_pe),
            unit="x",
            detail=f"peer median {fmt_value(r2(med), 'x')} ({peer_note})" if med else None,
            source=src,
            as_of=at,
            score=s,
        )
    if f.price_to_book is not None:
        med = peer_median("price_to_book")
        s = valuation.add(scale(1 - f.price_to_book / med, -0.5, 0.5)) if med else None
        b.evidence(
            "Valuation",
            "Price/book",
            r2(f.price_to_book),
            unit="x",
            detail=f"peer median {fmt_value(r2(med), 'x')}" if med else None,
            source=src,
            as_of=at,
            score=s,
        )
    if f.forward_pe is not None:
        b.evidence("Valuation", "P/E (forward)", r2(f.forward_pe), unit="x", source=src, as_of=at)
    if valuation.score is None:
        b.gap("Valuation: fewer than three peers with comparable multiples.")

    # Profitability: absolute return on equity, margin relative to peers.
    if f.roe is not None:
        s = profitability.add(scale(f.roe, 0.05, 0.20))
        b.evidence(
            "Profitability",
            "Return on equity",
            pct(f.roe),
            unit="%",
            detail="net income / (book value per share x shares)" if f.roe_derived else None,
            source=src,
            as_of=at,
            score=s,
        )
    if f.profit_margin is not None:
        med = peer_median("profit_margin")
        s = profitability.add(scale(f.profit_margin / med - 1, -0.5, 0.5)) if med else None
        b.evidence(
            "Profitability",
            "Net margin",
            pct(f.profit_margin),
            unit="%",
            detail=f"peer median {fmt_value(pct(med), '%')}" if med else None,
            source=src,
            as_of=at,
            score=s,
        )
    if f.operating_margin is not None:
        b.evidence(
            "Profitability", "Operating margin", pct(f.operating_margin), unit="%", source=src
        )

    # Growth: latest reported year-on-year quarterly growth.
    quarter = f.most_recent_quarter
    q_note = f"quarter ended {quarter:%d %b %Y}" if quarter else None
    if f.revenue_growth is not None:
        s = growth.add(scale(f.revenue_growth, -0.05, 0.20))
        b.evidence(
            "Growth",
            "Revenue growth (YoY)",
            pct(f.revenue_growth),
            unit="%",
            detail=q_note,
            source=src,
            as_of=at,
            score=s,
        )
    if f.earnings_growth is not None:
        s = growth.add(scale(f.earnings_growth, -0.15, 0.30))
        b.evidence(
            "Growth",
            "Earnings growth (YoY)",
            pct(f.earnings_growth),
            unit="%",
            detail=q_note,
            source=src,
            as_of=at,
            score=s,
        )

    # Balance sheet.
    if ctx.industry in LENDERS:
        balance.weight = 0.0
        balance.note = "Not scored for lenders"
    elif f.debt_to_equity is not None:
        s = balance.add(scale(f.debt_to_equity, 1.5, 0.0))
        b.evidence(
            "Balance sheet",
            "Debt/equity",
            r2(f.debt_to_equity),
            unit="x",
            source=src,
            as_of=at,
            score=s,
        )
    if f.dividend_yield is not None:
        b.evidence("Balance sheet", "Dividend yield", pct(f.dividend_yield), unit="%", source=src)
    for factor in (profitability, growth, balance):
        if factor.score is None and factor.weight > 0:
            b.gap(f"{factor.name}: not reported by the fundamentals source.")


def _technicals(b: AgentBuilder, ctx: ResearchContext) -> None:
    tech = b.factor("Technicals", 0.25)
    s = ctx.stock
    if s is None or len(s.closes) < 60:
        b.gap(f"Technicals: daily prices unavailable ({ctx.problems.get('prices', 'no data')}).")
        return
    c, src, at = s.closes, s.source, s.as_of
    last = c[-1]
    sma200, sma50 = ta.sma(c, 200), ta.sma(c, 50)
    if sma200:
        dist = last / sma200 - 1
        b.evidence(
            "Technicals",
            "Price vs 200-day average",
            pct(dist),
            unit="%",
            detail=f"200-day average {fmt_value(r2(sma200), 'INR')}",
            source=src,
            as_of=at,
            score=tech.add(scale(dist, -0.15, 0.15)),
        )
    if sma50 and sma200:
        gap = sma50 / sma200 - 1
        b.evidence(
            "Technicals",
            "50-day vs 200-day average",
            pct(gap),
            unit="%",
            source=src,
            as_of=at,
            score=tech.add(scale(gap, -0.05, 0.05)),
        )
    mom = ta.period_return(c, 126)
    if mom is not None:
        b.evidence(
            "Technicals",
            "6-month return",
            pct(mom),
            unit="%",
            source=src,
            as_of=at,
            score=tech.add(scale(mom, -0.2, 0.2)),
        )
    rsi = ta.rsi(c)
    if rsi is not None:
        zone = "overbought" if rsi >= 70 else "oversold" if rsi <= 30 else "neutral band"
        b.evidence("Technicals", "RSI (14)", r2(rsi), detail=zone, source=src, as_of=at)
    vol = ta.annualized_volatility(c)
    if vol is not None:
        b.evidence("Risk", "Volatility (6M, annualised)", pct(vol), unit="%", source=src)
    dd = ta.max_drawdown(c)
    if dd is not None:
        b.evidence("Risk", "Max drawdown (1Y)", pct(dd), unit="%", source=src)
    if ctx.benchmark is not None:
        a, m = ta.align_closes(s.pairs, ctx.benchmark.pairs)
        bt = ta.beta(a, m)
        if bt is not None:
            b.evidence("Risk", "Beta vs NIFTY 50 (1Y)", r2(bt), source=src)
