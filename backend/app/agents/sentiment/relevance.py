"""Financial relevance screening for the Sentiment Analyst.

Problem: provider search (`"Company Name" OR SYMBOL`) returns anything that
merely mentions the ticker — sponsored marathons, HR anecdotes, tragedies,
market digests, even common-noun collisions ("weighing reliance on Stripe").
Scoring those as company sentiment fabricates signal from noise.

Rule (deterministic, lexical, no ML, no new dependencies): an article is
relevant only if it BOTH

1. **identifies the company** — full legal name (substring) or a curated
   alias / ticker (whole-word for single tokens), AND
2. **carries financial/business context** — at least one term from the
   documented FINANCIAL_KEYWORDS set (earnings, deals, leadership, market
   action, regulatory, money), AND
3. is not about an **excluded topic** (sport/sponsorship events run under the
   company's brand — e.g. the TCS Sydney Marathon — which mention the ticker
   but carry no investment signal).

Design notes:

- The identity gate does the heavy lifting: generic financial words are safe
  because they only count next to a company mention.
- Single-token identifiers shorter than 3 characters are never bare-matched
  (e.g. "LT" would collide constantly); such companies must match via a
  longer alias ("L&T") or the full name. Bare forms that collide with common
  words are excluded in `universe_config` per company, with reasons — except
  case-sensitive brand tokens in `strict_aliases` (capitalized `Reliance` =
  the company, lowercase `reliance` = the common noun).
- Personnel-history mentions ("bhatt, who previously served as chairman of
  …, State Bank of India") are disqualified as former-affiliation bio-lines,
  not stories about the company. Bare "ex-" is deliberately not a marker so
  ex-dividend/ex-bonus headlines keep working.
- Multi-word identifiers and punctuated tokens ("L&T", "Reliance Jio") match
  as case-insensitive substrings; single alphanumeric tokens match as whole
  words so "TCS" never fires inside "switches".
- Verdicts carry machine-readable `reason` codes (`relevant`,
  `no_identity`, `no_financial_context`, `excluded_topic`) plus the exact
  matched terms, so the agent can report retrieved/considered/rejected counts
  and show *why* articles were excluded. Nothing is random; identical stored
  articles always produce identical verdicts.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# -- financial/business context vocabulary ------------------------------------
#
# Grouped for documentation; matching is a flat whole-word (or phrase)
# lookup over title + description (+ content when present). Deliberately
# EXCLUDED as too generic even beside a company mention: payment,
# infrastructure, bank/banks, building, technology, service(s), business
# (all routine company descriptors, not events).

FINANCIAL_KEYWORDS: frozenset[str] = frozenset(
    [
        # earnings & results
        "earnings", "results", "result", "quarter", "quarterly",
        "q1", "q2", "q3", "q4", "h1", "fy", "fiscal",
        "revenue", "revenues", "income", "profit", "profits",
        "loss", "losses", "ebitda", "ebit", "margin", "margins",
        "pat", "net", "topline", "bottomline", "bottom line",
        "beat", "beats", "beating", "miss", "misses",
        "estimate", "estimates", "guidance", "outlook", "forecast",
        "growth", "demand",
        # corporate actions & business development
        "deal", "deals", "contract", "contracts", "order", "orders",
        "acquisition", "acquisitions", "acquire", "merger", "mergers",
        "takeover", "buyout", "buyback", "dividend", "dividends",
        "bonus", "split", "ipo", "listing", "stake", "stakes",
        "investment", "investments", "funding", "fundraising",
        "capex", "expansion", "launch", "launches", "enterprise",
        "platform", "bond", "bonds",
        "partnership", "partnerships", "partner", "collaboration",
        "tie-up", "tieup", "alliance", "pact", "venture",
        "award", "awards", "win", "wins", "won", "bag", "bags",
        # leadership & workforce
        "ceo", "cfo", "chairman", "resign", "resigns", "resigned",
        "resignation", "step down", "steps down", "appoint",
        "appoints", "appointed", "successor", "layoff", "layoffs",
        "job cut", "job cuts", "firing", "fired", "hiring", "attrition",
        # market action & analyst views
        "shares", "share", "stock", "stocks", "equity", "equities",
        "rally", "rallies", "rallied", "surge", "surges", "surged",
        "jump", "jumps", "jumped", "zoom", "zooms", "soar", "soars",
        "soared", "plunge", "plunges", "plunged", "tumble",
        "tumbles", "tumbled", "slide", "slides", "gain", "gains",
        "gained", "gainer", "gainers", "fall", "falls", "fell",
        "drop", "drops", "dropped", "rise", "rises", "rose",
        "climb", "climbs", "sink", "sinks", "upgrade", "upgrades",
        "upgraded", "downgrade", "downgrades", "downgraded",
        "overweight", "underweight", "outperform", "record",
        "valuation", "valuations", "market cap",
        "target price", "price target", "buy call", "sell call",
        "hold call", "all-time high", "all time high", "52-week",
        "rate cut", "rate cuts", "rate hike", "record high",
        "record profit",
        # regulatory / legal / policy
        "sebi", "rbi", "fine", "fines", "fined", "penalty",
        "penalties", "lawsuit", "probe", "probes", "investigation",
        "scam", "fraud", "approval", "approvals", "license",
        "licence", "tariff", "tariffs", "ban", "banned", "duty",
        "duties", "regulation", "regulations", "regulator",
        "court", "tribunal", "nclt", "show-cause", "show cause",
        "settlement",
        # money
        "crore", "crores", "lakh", "lakhs", "million", "billion",
        "trillion", "$", "₹", "rs", "rupee", "rupees",
    ]
)

# Topics that mention the brand but carry no investment signal. Checked
# FIRST: an excluded topic rejects the article even if a financial term also
# appears (e.g. a marathon "record"). Kept tight — generic words like
# "match"/"game" are excluded from this list because they collide with
# financial phrasing ("match estimates").
EXCLUDED_TOPICS: frozenset[str] = frozenset(
    [
        "marathon", "marathons", "cricket", "cricketer", "football",
        "footballer", "ipl", "olympic", "olympics", "sponsor",
        "sponsors", "sponsored", "sponsorship", "tournament",
        "tournaments", "wimbledon", "world cup", "asia cup",
        # branded road-race series run under the company name
        # (e.g. "TCS World 10K") — sponsorship, not signal.
        "10k",
        # other brand-sponsored sport (e.g. company golf championships).
        "golf", "golfer", "tennis", "badminton", "hockey",
        "kabaddi", "chess", "boxing", "wrestler", "wrestling",
        # personal tragedies/accidents involving employees ("TCS techie
        # dies…"): identity matches, but there is no investment signal.
        # ("dead" never fires inside "deadline" — whole-word matching.)
        "dies", "dead", "death", "deaths", "killed", "kills",
        "killing", "accident", "accidents", "murder", "suicide",
    ]
)

# Retail-discount flyers where a brand acronym collides with the company
# (e.g. Harbor Freight's "Inside Track Club" sales matching bare "ITC").
# A percentage-off figure combined with "sale" is a promo, not news.
EXCLUDED_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)\bsale\b.{0,80}\d+\s*%\s*off|\d+\s*%\s*off.{0,80}\bsale\b"),
)

#: Minimum token length for bare whole-word identifier matching.
MIN_BARE_TOKEN_LEN = 3

# Personnel-history markers: an identity mention preceded (within the window)
# by one of these is a bio-line reference ("..., previously chairman of X"),
# not a story about the company — the occurrence is disqualified. Whole-word,
# personnel-only by design: "ex-dividend"/"ex-bonus" headlines must keep
# working, so bare "ex-" is deliberately NOT a marker.
FORMER_AFFILIATION_MARKERS = re.compile(
    r"\b(former|formerly|previously|erstwhile)\b"
)
FORMER_AFFILIATION_WINDOW = 80


@dataclass(frozen=True)
class RelevanceVerdict:
    """One deterministic relevance decision."""

    relevant: bool
    identity_hit: str | None
    financial_hit: str | None
    reason: str  # "relevant" | "no_identity" | "no_financial_context" | "excluded_topic"


def _contains_token(
    haystack_lower: str,
    raw_text: str,
    token: str,
    strict: bool = False,
    min_bare_len: int = MIN_BARE_TOKEN_LEN,
) -> bool:
    """Token match over case-folded text: substring for multi-word/punctuated
    tokens, whole-word for single alphanumeric tokens. `min_bare_len` floors
    bare matching (company identifiers use 3 to defeat two-letter noise like
    bare "LT"; short financial codes like "q1"/"rs" pass 0). Strict tokens
    additionally require the capitalized surface form in the original text —
    defeats lowercase common-noun uses such as "banks' reliance on deposits"."""
    token = (token or "").strip()
    if not token:
        return False
    lowered = token.lower()
    if " " in token or any(not ch.isalnum() for ch in token):
        hit = lowered in haystack_lower
    elif len(token) < min_bare_len:
        return False
    else:
        hit = re.search(rf"\b{re.escape(lowered)}\b", haystack_lower) is not None
    if hit and strict:
        return re.search(rf"\b{re.escape(token)}\b", raw_text or "") is not None
    return hit


def company_identifiers(entry) -> list[tuple[str, bool]]:
    """Ordered (pattern, strict) match patterns for a universe entry: legal
    name, curated aliases, strict aliases, internal symbol, and
    provider-ticker base (e.g. TCS.NS → TCS)."""
    ordered: list[tuple[str, bool]] = []
    seen: set[str] = set()

    def add(pattern: str | None, strict: bool = False) -> None:
        key = ((pattern or "").strip(), strict)
        lowered = key[0].lower()
        if lowered and lowered not in seen:
            seen.add(lowered)
            ordered.append(((pattern or "").strip(), strict))

    add(entry.name)
    for alias in entry.aliases or []:
        add(alias)
    for alias in getattr(entry, "strict_aliases", None) or []:
        add(alias, strict=True)
    add(entry.symbol)
    ticker_base = (entry.ticker or "").split(".")[0]
    if ticker_base and ticker_base.upper() != entry.symbol.upper():
        add(ticker_base)
    return ordered


def _is_former_affiliation(haystack_lower: str, match_start: int) -> bool:
    """True when a personnel-history marker sits just before the match."""
    context = haystack_lower[max(0, match_start - FORMER_AFFILIATION_WINDOW):match_start]
    return FORMER_AFFILIATION_MARKERS.search(context) is not None


def find_identity_hit(text: str, identifiers: list[tuple[str, bool]]) -> str | None:
    """First matching company identifier, or None.

    Occurrences disqualified as former-affiliation bio-lines are skipped in
    favour of later genuine occurrences of the same or another identifier.
    """
    lowered = (text or "").lower()
    raw = text or ""
    for ident, strict in identifiers:
        token = (ident or "").strip()
        if not token:
            continue
        lowered_tok = token.lower()
        if " " in token or any(not ch.isalnum() for ch in token):
            start = 0
            while True:
                i = lowered.find(lowered_tok, start)
                if i < 0:
                    break
                if not _is_former_affiliation(lowered, i):
                    if not strict or raw[i:i + len(token)] == token:
                        return ident
                start = i + 1
        elif len(token) >= MIN_BARE_TOKEN_LEN:
            for m in re.finditer(rf"\b{re.escape(lowered_tok)}\b", lowered):
                if _is_former_affiliation(lowered, m.start()):
                    continue
                if strict and raw[m.start():m.end()] != token:
                    continue
                return ident
    return None


def find_financial_hit(text: str) -> str | None:
    """First matching financial-context term, or None."""
    lowered = (text or "").lower()
    for term in sorted(FINANCIAL_KEYWORDS):
        if _contains_token(lowered, text or "", term, min_bare_len=0):
            return term
    return None


def find_excluded_topic(text: str) -> str | None:
    """First matching excluded topic or promo pattern, or None."""
    lowered = (text or "").lower()
    for topic in sorted(EXCLUDED_TOPICS):
        if _contains_token(lowered, text or "", topic, min_bare_len=0):
            return topic
    for pattern in EXCLUDED_PATTERNS:
        if pattern.search(text or ""):
            return "retail promo"
    return None


def assess_relevance(
    title: str | None,
    description: str | None,
    content: str | None,
    entry,
) -> RelevanceVerdict:
    """Decide whether an article is analyzable company news.

    Identity is matched over title + description + content; financial context
    and excluded topics over title + description (the editorial summary —
    truncated provider content blobs add noise, not signal).
    """
    identifiers = company_identifiers(entry)
    identity_text = " ".join(p for p in (title, description, content) if p)
    summary_text = " ".join(p for p in (title, description) if p)

    excluded = find_excluded_topic(summary_text)
    identity_hit = find_identity_hit(identity_text, identifiers)
    financial_hit = find_financial_hit(summary_text)

    if excluded is not None:
        return RelevanceVerdict(False, identity_hit, financial_hit, "excluded_topic")
    if identity_hit is None:
        return RelevanceVerdict(False, None, financial_hit, "no_identity")
    if financial_hit is None:
        return RelevanceVerdict(False, identity_hit, None, "no_financial_context")
    return RelevanceVerdict(True, identity_hit, financial_hit, "relevant")
