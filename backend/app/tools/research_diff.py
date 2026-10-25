"""What changed between two research reports for the same stock. Pure functions, no I/O."""

from app.agents.base import fmt_value
from app.schemas.research import Change, ResearchChanges, ResearchReport

AGENT_LABEL = {
    "composite": "Overall",
    "firm": "Company",
    "industry": "Industry",
    "macro": "Macro",
    "sentiment": "News sentiment",
}
SIGNAL_LABEL = {
    "positive": "positive",
    "neutral": "neutral",
    "negative": "negative",
    "insufficient_data": "not enough data",
}
_RANK = {"negative": -1, "neutral": 0, "positive": 1}
SCORE_STEP = 0.10  # agent and composite scores, -1..1
FACTOR_STEP = 0.25  # factor scores move in coarser steps
METRIC_STEP = 0.10  # relative change in a scored metric
MAX_ITEMS = 8


def _direction(before: float | None, after: float | None) -> str:
    if before is None or after is None or before == after:
        return "neutral"
    return "better" if after > before else "worse"


def _signal_direction(before: str, after: str) -> str:
    if before in _RANK and after in _RANK:
        return _direction(_RANK[before], _RANK[after])
    return "neutral"


def diff_reports(old: ResearchReport, new: ResearchReport) -> ResearchChanges:
    items: list[Change] = []
    oc, nc = old.composite, new.composite
    if oc.signal != nc.signal:
        items.append(
            Change(
                agent="composite",
                kind="signal",
                text=f"Overall view changed from {SIGNAL_LABEL[oc.signal]} to "
                f"{SIGNAL_LABEL[nc.signal]}.",
                direction=_signal_direction(oc.signal, nc.signal),
                weight=4.0,
            )
        )
    elif oc.score is not None and nc.score is not None and abs(nc.score - oc.score) >= SCORE_STEP:
        items.append(
            Change(
                agent="composite",
                kind="score",
                text=f"Overall score moved from {oc.score:+.2f} to {nc.score:+.2f}.",
                direction=_direction(oc.score, nc.score),
                weight=3.0,
            )
        )

    previous = {a.agent: a for a in old.agents}
    for a in new.agents:
        o = previous.get(a.agent)
        if o is None:
            continue
        name = AGENT_LABEL[a.agent]
        if o.signal != a.signal:
            items.append(
                Change(
                    agent=a.agent,
                    kind="signal",
                    text=f"{name} view changed from {SIGNAL_LABEL[o.signal]} to "
                    f"{SIGNAL_LABEL[a.signal]}.",
                    direction=_signal_direction(o.signal, a.signal),
                    weight=2.5,
                )
            )
        elif o.score is not None and a.score is not None and abs(a.score - o.score) >= SCORE_STEP:
            items.append(
                Change(
                    agent=a.agent,
                    kind="score",
                    text=f"{name} score moved from {o.score:+.2f} to {a.score:+.2f}.",
                    direction=_direction(o.score, a.score),
                    weight=1.5 + abs(a.score - o.score),
                )
            )
        old_factors = {f.name: f for f in o.factors}
        for f in a.factors:
            p = old_factors.get(f.name)
            if p is None or f.weight == 0:
                continue
            if p.score is not None and f.score is not None:
                if abs(f.score - p.score) >= FACTOR_STEP:
                    items.append(
                        Change(
                            agent=a.agent,
                            kind="factor",
                            text=f"{name}: {f.name.lower()} moved from {p.score:+.2f} to "
                            f"{f.score:+.2f}.",
                            direction=_direction(p.score, f.score),
                            weight=1.0 + abs(f.score - p.score),
                        )
                    )
            elif (p.score is None) != (f.score is None):
                text = "now has data" if f.score is not None else "no longer has data"
                items.append(
                    Change(
                        agent=a.agent,
                        kind="factor",
                        text=f"{name}: {f.name.lower()} {text}.",
                        weight=0.9,
                    )
                )
        old_evidence = {(e.factor, e.metric): e for e in o.evidence}
        for e in a.evidence:
            p = old_evidence.get((e.factor, e.metric))
            if (
                p is None
                or e.score is None
                or not isinstance(e.value, int | float)
                or not isinstance(p.value, int | float)
                or e.value == p.value
            ):
                continue
            rel = abs(e.value - p.value) / max(abs(p.value), 1e-9)
            if rel >= METRIC_STEP:
                items.append(
                    Change(
                        agent=a.agent,
                        kind="metric",
                        text=f"{e.metric}: {fmt_value(p.value, e.unit)} to "
                        f"{fmt_value(e.value, e.unit)}.",
                        direction=_direction(p.score, e.score),
                        weight=0.5 + min(rel, 1.0),
                    )
                )

    seen = {h.title.casefold() for h in old.headlines}
    fresh = [h for h in new.headlines if h.title.casefold() not in seen]
    if fresh:
        items.append(
            Change(
                agent="sentiment",
                kind="headlines",
                text=f"{len(fresh)} new headline{'s' if len(fresh) != 1 else ''}, latest: "
                f"“{fresh[0].title}”.",
                weight=0.8,
            )
        )

    items.sort(key=lambda c: -c.weight)
    items = items[:MAX_ITEMS]
    if not items:
        summary = "No material change."
    else:
        summary = items[0].text
        if len(items) > 1:
            summary += f" {len(items) - 1} other change{'s' if len(items) > 2 else ''}."
    return ResearchChanges(
        since=old.computed_at,
        until=new.computed_at,
        previous_signal=oc.signal,
        previous_score=oc.score,
        summary=summary,
        items=items,
    )
