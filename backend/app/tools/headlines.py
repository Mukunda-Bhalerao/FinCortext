"""Deterministic headline tone and event tagging with a small finance word list.

Each headline scores (positive terms - negative terms) / (positive + negative terms), with a
preceding negation ("no", "not", "without") flipping a term. The matched terms are returned so
every score can be traced back to the words that produced it.
"""

import re
from dataclasses import dataclass

LEXICON_VERSION = "headline-lexicon-v1"

POSITIVE = frozenset(
    """
    beat beats surge surges surged soar soars soared jump jumps jumped rally rallies rallied
    gain gains gained rise rises rose record high highs upgrade upgraded upgrades outperform
    outperforms growth grows grew expand expands expansion profit profits profitable strong
    stronger robust boost boosts boosted win wins won bags secures secured approval approved
    dividend buyback bonus recovery rebound rebounds rebounded beat-estimates bullish upbeat
    optimistic accelerate accelerates momentum milestone breakthrough
    """.split()
)
NEGATIVE = frozenset(
    """
    miss misses missed fall falls fell drop drops dropped slump slumps slumped plunge plunges
    plunged crash crashes tumble tumbles tumbled decline declines declined loss losses weak
    weaker downgrade downgraded downgrades underperform cut cuts slash slashes probe penalty
    fine fined raid raids fraud default defaults lawsuit ban banned halt halted resigns
    resignation exit exits concern concerns warning warns bearish pressure slowdown slows
    slowed sell-off selloff shortfall delay delayed delays scam investigation notice dip dips
    """.split()
)
NEGATIONS = frozenset({"no", "not", "without", "never", "fails", "failed"})

EVENT_TERMS: dict[str, frozenset[str]] = {
    "Results": frozenset({"results", "earnings", "quarterly", "q1", "q2", "q3", "q4", "profit"}),
    "Dividend or buyback": frozenset({"dividend", "buyback", "bonus", "split"}),
    "Order or contract": frozenset({"order", "orders", "contract", "bags", "secures", "deal"}),
    "M&A or stake": frozenset({"acquire", "acquires", "acquisition", "merger", "stake"}),
    "Rating or target": frozenset({"upgrade", "downgrade", "target", "rating", "brokerage"}),
    "Regulatory or legal": frozenset(
        {"sebi", "rbi", "penalty", "probe", "raid", "fine", "notice", "lawsuit", "court", "ban"}
    ),
    "Management": frozenset({"ceo", "cfo", "md", "resigns", "appoints", "chairman", "board"}),
}

_TOKEN = re.compile(r"[a-z0-9&]+(?:-[a-z0-9]+)*")


@dataclass(frozen=True)
class HeadlineScore:
    score: float  # -1..1, 0 when no term matched
    positive: tuple[str, ...]
    negative: tuple[str, ...]
    events: tuple[str, ...]


def score_headline(title: str) -> HeadlineScore:
    tokens = _TOKEN.findall(title.lower())
    pos: list[str] = []
    neg: list[str] = []
    for i, tok in enumerate(tokens):
        negated = i > 0 and tokens[i - 1] in NEGATIONS
        if tok in POSITIVE:
            (neg if negated else pos).append(tok)
        elif tok in NEGATIVE:
            (pos if negated else neg).append(tok)
    hits = len(pos) + len(neg)
    words = set(tokens)
    events = tuple(name for name, terms in EVENT_TERMS.items() if words & terms)
    return HeadlineScore(
        score=(len(pos) - len(neg)) / hits if hits else 0.0,
        positive=tuple(pos),
        negative=tuple(neg),
        events=events,
    )


def recency_weight(age_days: float, half_life_days: float = 7.0) -> float:
    return 0.5 ** (max(0.0, age_days) / half_life_days)


_SUFFIXES = re.compile(r"\b(ltd|limited|inc|corp|corporation|co|company|the)\b\.?", re.I)


def name_terms(name: str | None, symbol: str) -> list[str]:
    """Terms a headline must contain to count as being about the company."""
    terms = {symbol.lower()}
    if name:
        cleaned = " ".join(_SUFFIXES.sub(" ", name).split())
        if cleaned:
            terms.add(cleaned.lower())
            first = cleaned.split()[0].lower()
            if len(first) >= 4:
                terms.add(first)
    return sorted(terms)


def is_relevant(title: str, terms: list[str]) -> bool:
    lowered = f" {title.lower()} "
    return any(re.search(rf"(?<![a-z0-9]){re.escape(t)}(?![a-z0-9])", lowered) for t in terms)
