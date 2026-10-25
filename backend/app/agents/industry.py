"""Industry analyst: sector momentum, peer standing, breadth and competitive structure.

Factor weights: sector relative strength 0.30, sector trend 0.15, peer rank 0.30,
peer breadth 0.25. Peers are NIFTY 500 members in the same NSE industry.
"""

from app.agents.base import AgentBuilder, ResearchContext, fmt_value, pct, r2
from app.providers import yahoo
from app.schemas.research import AgentOutput
from app.tools import technicals as ta
from app.tools.scoring import percentile_rank, scale

METHOD = "industry-v1"
MIN_PEERS = 4


def run(ctx: ResearchContext) -> AgentOutput:
    b = AgentBuilder("industry", ctx.industry or ctx.instrument.symbol, METHOD, ctx.now)
    if ctx.industry:
        b.evidence(
            "Structure",
            "Industry",
            ctx.industry,
            detail=f"sector benchmark {ctx.sector_label}" if ctx.sector_label else None,
            source=ctx.industry_source or "unknown",
        )
    else:
        b.gap("Industry classification unavailable for this company.")
    _sector(b, ctx)
    _peers(b, ctx)
    b.gap("Demand and outlook: no free source of industry demand data or forecasts; not scored.")
    return b.build()


def _sector(b: AgentBuilder, ctx: ResearchContext) -> None:
    rel = b.factor("Sector relative strength", 0.30)
    trend = b.factor("Sector trend", 0.15)
    sec, bench = ctx.sector, ctx.benchmark
    if sec is None:
        reason = ctx.problems.get("sector") or "no sector index mapped to this industry"
        b.gap(f"Sector index: {reason}.")
        return
    for months, n in ((3, 63), (6, 126)):
        r_sec = ta.period_return(sec.closes, n)
        r_bench = ta.period_return(bench.closes, n) if bench else None
        if r_sec is None:
            continue
        diff = r_sec - r_bench if r_bench is not None else None
        b.evidence(
            "Sector relative strength",
            f"{sec.label} {months}M return",
            pct(r_sec),
            unit="%",
            detail=f"NIFTY 50 {fmt_value(pct(r_bench), '%')}" if r_bench is not None else None,
            source=sec.source,
            as_of=sec.as_of,
            score=rel.add(scale(diff, -0.08, 0.08)) if diff is not None else None,
        )
    sma200 = ta.sma(sec.closes, 200)
    if sma200:
        dist = sec.closes[-1] / sma200 - 1
        b.evidence(
            "Sector trend",
            f"{sec.label} vs 200-day average",
            pct(dist),
            unit="%",
            source=sec.source,
            as_of=sec.as_of,
            score=trend.add(scale(dist, -0.10, 0.10)),
        )


def _peers(b: AgentBuilder, ctx: ResearchContext) -> None:
    rank = b.factor("Peer rank", 0.30)
    breadth = b.factor("Peer breadth", 0.25)
    priced = [p for p in ctx.peers if p.series is not None and len(p.series.closes) > 127]
    if len(priced) < MIN_PEERS:
        reason = ctx.problems.get("peers") or f"{len(priced)} peers with a price history"
        b.gap(f"Peer comparison needs at least {MIN_PEERS} peers: {reason}.")
    else:
        src = priced[0].series.source  # type: ignore[union-attr]
        stock = ctx.stock
        own = ta.period_return(stock.closes, 126) if stock else None
        returns = [ta.period_return(p.series.closes, 126) for p in priced]  # type: ignore[union-attr]
        population = [r for r in returns if r is not None]
        if own is not None and population:
            p = percentile_rank(own, population)
            b.evidence(
                "Peer rank",
                "6-month return percentile among peers",
                round(p * 100),
                unit="%",
                detail=f"own return {fmt_value(pct(own), '%')} vs {len(population)} peers",
                source=src,
                as_of=stock.as_of if stock else None,
                score=rank.add(scale(p, 0.0, 1.0)),
            )
        above = [
            p for p in priced if (m := ta.sma(p.series.closes, 50)) and p.series.closes[-1] > m
        ]  # type: ignore[union-attr]
        share = len(above) / len(priced)
        b.evidence(
            "Peer breadth",
            "Peers above 50-day average",
            round(share * 100),
            unit="%",
            detail=f"{len(above)} of {len(priced)}",
            source=src,
            score=breadth.add(scale(share, 0.2, 0.8)),
        )
    # Competitive structure from market capitalisation (evidence only).
    caps = [
        (p.instrument.symbol, p.fundamentals.market_cap)
        for p in ctx.peers
        if p.fundamentals and p.fundamentals.market_cap
    ]
    own_cap = ctx.fundamentals.market_cap if ctx.fundamentals else None
    if own_cap and len(caps) >= MIN_PEERS - 1:
        group = sorted([c for _, c in caps] + [own_cap], reverse=True)
        total = sum(group)
        hhi = sum((c / total) ** 2 for c in group) * 10_000
        b.evidence(
            "Structure",
            "Market-cap rank in peer set",
            f"{group.index(own_cap) + 1} of {len(group)}",
            detail=f"{fmt_value(pct(own_cap / total), '%')} of peer-set market cap",
            source=yahoo.SOURCE,
        )
        b.evidence(
            "Structure",
            "Peer-set concentration (HHI)",
            r2(hhi),
            detail="above 2,500 = concentrated",
            source=yahoo.SOURCE,
        )
    if ctx.peers:
        b.evidence(
            "Structure",
            "Peers compared",
            ", ".join(p.instrument.symbol for p in ctx.peers),
            detail=ctx.peer_basis,
            source="NSE NIFTY 500 constituents",
        )
