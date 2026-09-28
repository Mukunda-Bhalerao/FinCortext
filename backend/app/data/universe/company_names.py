"""Company-name utilities shared by retrieval and relevance.

Suffix stripping is used in two places with different strictness needs, so it
lives here once:
- retrieval queries (NewsService variants, RSS provider): short names widen
  recall ("ADANI POWER LTD" -> "Adani Power");
- relevance auto-aliases (relevance.py): the same short forms become identity
  patterns, with single common-noun words kept case-sensitive/strict there.
"""

from __future__ import annotations

# Trailing corporate suffixes stripped to derive a short company name
# ("Adani Power Limited" -> "Adani Power"). Single-word remainders
# ("Reliance", "Titan", "Page") are kept here too — relevance.py marks
# single common-noun words case-sensitive/strict, so precision is preserved
# by the matcher, not by dropping the alias.
CORP_SUFFIXES = {
    "LTD", "LTD.", "LIMITED", "PVT", "PVT.", "PRIVATE", "INDIA",
    "CORPORATION", "CORP", "CORP.", "INC", "INC.", "COMPANY", "CO", "CO.",
    "ENTERPRISES", "ENTERPRISE", "INDUSTRIES", "INDUSTRY", "GROUP", "AND",
}


def short_company_name(name: str) -> str:
    """Short display name for retrieval queries; original when irreducible."""
    tokens = (name or "").strip().split()
    while len(tokens) > 1 and tokens[-1].strip(".,").upper() in CORP_SUFFIXES:
        tokens.pop()
    short = " ".join(tokens).strip()
    return short or (name or "").strip()


def name_word_variants(name: str) -> list[str]:
    """Ordered name forms for identity matching: full, short, &/and swaps.

    De-duplicated, order kept. Empty input yields [].
    """
    forms: list[str] = []
    seen: set[str] = set()

    def add(form: str | None) -> None:
        text = (form or "").strip()
        if text and text.upper() not in seen:
            seen.add(text.upper())
            forms.append(text)

    full = (name or "").strip()
    add(full)
    short = short_company_name(name)
    add(short)
    for form in list(forms):
        if " & " in form:
            add(form.replace(" & ", " and "))
        if " and " in form.lower():
            import re

            add(re.sub(r"(?i)\band\b", "&", form, count=10))
    # First-two-words form for long names ("Bharat Petroleum Corporation"
    # is already 2 words after stripping; "Oil & Natural Gas ..." keeps "&"
    # forms above instead of a misleading "Oil &" cut).
    tokens = short.split()
    if len(tokens) > 2 and tokens[1] not in {"&", "and", "AND"}:
        add(" ".join(tokens[:2]))
    return forms
