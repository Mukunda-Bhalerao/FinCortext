"""Sentiment analyst: news tone, analyst consensus, price-target gap and event signals.

Factor weights: news tone 0.50, analyst consensus 0.30, target gap 0.20. Headline tone uses
the deterministic word list in ``tools.headlines``, weighted by recency (7-day half-life).
"""

from collections import Counter

from app.agents.base import AgentBuilder, ResearchContext, fmt_value, pct, r2
from app.providers import yahoo
from app.schemas.research import AgentOutput
from app.tools.headlines import LEXICON_VERSION, recency_weight, score_headline
from app.tools.scoring import scale

METHOD = "sentiment-v1"
MIN_HEADLINES = 3
MIN_ANALYSTS = 3
NEWS_SOURCE = "Google News RSS search"


def run(ctx: ResearchContext) -> AgentOutput:
    b = AgentBuilder("sentiment", ctx.instrument.symbol, METHOD, ctx.now)
    _news(b, ctx)
    _analysts(b, ctx)
    b.gap("Social media sentiment: no free, terms-compliant social data source; not scored.")
    return b.build()


def _news(b: AgentBuilder, ctx: ResearchContext) -> None:
    tone = b.factor("News tone", 0.5)
    items = ctx.headlines
    if len(items) < MIN_HEADLINES:
        reason = ctx.problems.get("news") or f"{len(items)} relevant headlines in 30 days"
        b.gap(f"News tone needs at least {MIN_HEADLINES} headlines: {reason}.")
        if not items:
            return
    num = den = 0.0
    pos = neg = 0
    events: Counter[str] = Counter()
    for item in items:
        hs = score_headline(item.title)
        age = (ctx.now - item.published_at).total_seconds() / 86400 if item.published_at else 30
        w = recency_weight(age)
        num += w * hs.score
        den += w
        pos += hs.score > 0
        neg += hs.score < 0
        events.update(hs.events)
    weighted_tone = num / den if den else 0.0
    newest = max((i.published_at for i in items if i.published_at), default=None)
    b.evidence(
        "News tone",
        "Recency-weighted headline tone",
        r2(weighted_tone),
        detail=f"{len(items)} headlines: {pos} positive, {neg} negative ({LEXICON_VERSION})",
        source=NEWS_SOURCE,
        as_of=newest,
        score=tone.add(scale(weighted_tone, -0.4, 0.4)) if len(items) >= MIN_HEADLINES else None,
    )
    for name, count in events.most_common(4):
        b.evidence(
            "Event signals",
            name,
            count,
            unit="count",
            detail="headlines in the last 30 days",
            source=NEWS_SOURCE,
        )


def _analysts(b: AgentBuilder, ctx: ResearchContext) -> None:
    consensus = b.factor("Analyst consensus", 0.3)
    target = b.factor("Target gap", 0.2)
    f = ctx.fundamentals
    if f is None:
        b.gap(f"Analyst views unavailable: {ctx.problems.get('fundamentals', 'no data')}.")
        return
    src, at = yahoo.SOURCE, f.fetched_at
    count = f.analyst_count or 0
    if f.recommendation_mean is not None and count >= MIN_ANALYSTS:
        counts = f.rating_counts
        detail = (
            f"{counts.get('strongBuy', 0) + counts.get('buy', 0)} buy, {counts.get('hold', 0)} "
            f"hold, {counts.get('sell', 0) + counts.get('strongSell', 0)} sell"
            if counts
            else f"{count} analysts"
        )
        b.evidence(
            "Analyst consensus",
            "Mean rating (1 = strong buy, 5 = strong sell)",
            r2(f.recommendation_mean),
            detail=detail,
            source=src,
            as_of=at,
            score=consensus.add(scale(f.recommendation_mean, 3.5, 1.5)),
        )
    else:
        b.gap(f"Analyst consensus: {count} analyst opinions reported (minimum {MIN_ANALYSTS}).")
    price = ctx.stock.closes[-1] if ctx.stock and ctx.stock.closes else f.price
    if f.target_mean and price and count >= MIN_ANALYSTS:
        gap = f.target_mean / price - 1
        b.evidence(
            "Target gap",
            "Mean target vs last price",
            pct(gap),
            unit="%",
            detail=f"mean target {fmt_value(r2(f.target_mean), 'INR')}, {count} analysts",
            source=src,
            as_of=at,
            score=target.add(scale(gap, -0.05, 0.25)),
        )
    elif count >= MIN_ANALYSTS:
        b.gap("Target gap: no mean price target reported.")
