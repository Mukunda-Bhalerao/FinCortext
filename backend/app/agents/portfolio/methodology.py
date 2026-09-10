"""Portfolio Agent methodology — deterministic synthesis, fully documented.

The Portfolio Agent (Central Orchestrator) is NOT a fifth scoring model. It
reads the four existing analyst outputs for one company and explains how
they fit together. Every rule below is mechanical and testable; changing any
of them is a methodology change.

## Direction mapping (one common axis, vocabulary preserved)

Each perspective maps to positive (+1) / neutral (0) / negative (−1);
unavailable perspectives are EXCLUDED (never counted as neutral):

- firm / industry / sentiment: strong_buy, buy → +1; neutral → 0;
  sell, strong_sell → −1; unavailable (or null score) → excluded.
- macro: positive → +1; neutral → 0; negative → −1; unavailable → excluded.

The original signal wording is always preserved alongside (e.g. macro stays
"NEUTRAL-environment", never rewritten as a stock call).

## Agreement (no smoothing)

- Fewer than 2 available perspectives → "insufficient".
- All available share one direction → "unanimous-{positive|neutral|negative}".
- Otherwise the majority direction (> half of available) wins:
  "majority-positive" / "majority-negative"; no majority → "mixed".
- Every pair with opposite nonzero directions is listed as a conflict, named
  by perspective labels (e.g. "Firm Analyst vs Sentiment Analyst").

## Scenarios (conditional, grounded, never predictions)

- Base case: joins the current signals as stated.
- Bull case conditions: for each non-positive perspective, the concrete
  thing that would have to change (its top limitation or weakest factor);
  for missing perspectives, the input that would have to arrive.
- Bear case conditions: the mirror — what currently-positive perspectives
  depend on, plus existing risks.
- Each condition names real inputs (factors, limitations, coverage gaps),
  never invented catalysts.

## Thesis

A templated paragraph: how many of how many perspectives lean which way,
the strongest agreement or sharpest conflict, the best-supported view
(highest confidence available) and the weakest link (lowest confidence or
missing), plus the macro backdrop line. Deterministic string building from
the above — no language model, no sampling.

## Confidence and coverage

- coverage = available perspectives / 4.
- confidence = round(mean confidence of available perspectives × coverage, 2).
  Thin or partial evidence therefore caps confidence mechanically.
- Status: 0 available → UNAVAILABLE; fewer than 3 → DEGRADED; else OK.

## Evidence and risks

- Evidence lists one pointer per perspective used (agent, entity,
  generated_at, signal, score, status) plus the macro data-through map —
  every conclusion traces back to a stored output.
- Risks = every degraded/unavailable flag plus each perspective's own
  limitations (in full — truncation would hide caveats).
"""

from __future__ import annotations


# Buy-side / sell-side investment signals → direction.
BULLISH_SIGNALS = frozenset({"strong_buy", "buy"})
BEARISH_SIGNALS = frozenset({"sell", "strong_sell"})

# Macro environment signals → direction.
MACRO_BULLISH = frozenset({"positive"})
MACRO_BEARISH = frozenset({"negative"})

MIN_PERSPECTIVES_OK = 3  # fewer available perspectives → DEGRADED


def direction_of(kind: str, signal: str | None, score: float | None) -> str | None:
    """Map one perspective to positive/neutral/negative, or None if missing.

    `kind` is "analyst" (buy/sell vocabulary) or "macro" (environment
    vocabulary). A null score on an analyst output means unavailable even
    when a signal string is present.
    """
    if kind == "macro":
        if signal in MACRO_BULLISH:
            return "positive"
        if signal in MACRO_BEARISH:
            return "negative"
        if signal == "neutral":
            return "neutral"
        return None
    if signal is None or score is None:
        return None
    if signal in BULLISH_SIGNALS:
        return "positive"
    if signal in BEARISH_SIGNALS:
        return "negative"
    if signal == "neutral":
        return "neutral"
    return None


def agreement_of(directions: list[str]) -> tuple[str, str]:
    """(verdict, summary) for a list of available-perspective directions."""
    n = len(directions)
    if n < 2:
        return "insufficient", (
            "Fewer than two perspectives are available — agreement cannot "
            "be assessed."
        )
    pos = sum(1 for d in directions if d == "positive")
    neu = sum(1 for d in directions if d == "neutral")
    neg = sum(1 for d in directions if d == "negative")
    if pos == n:
        return "unanimous-positive", f"All {n} available perspectives lean positive."
    if neg == n:
        return "unanimous-negative", f"All {n} available perspectives lean negative."
    if neu == n:
        return "unanimous-neutral", f"All {n} available perspectives are neutral."
    if pos > n / 2:
        return "majority-positive", (
            f"{pos} of {n} available perspectives lean positive "
            f"({neg} negative, {neu} neutral)."
        )
    if neg > n / 2:
        return "majority-negative", (
            f"{neg} of {n} available perspectives lean negative "
            f"({pos} positive, {neu} neutral)."
        )
    return "mixed", (
        f"No majority: {pos} positive, {neu} neutral, {neg} negative "
        f"across {n} available perspectives."
    )


def combine_confidence(confidences: list[float], available: int, total: int = 4) -> float:
    """Mean available confidence, scaled by coverage. No available → 0.0."""
    if not confidences or available == 0:
        return 0.0
    coverage = available / total
    return round(sum(confidences) / len(confidences) * coverage, 2)
