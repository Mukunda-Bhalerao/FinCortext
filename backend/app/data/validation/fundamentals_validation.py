"""Validation for provider-supplied fundamental values.

Rules (documented; failures are reported with reasons, never silently
dropped and never repaired with invented values):

- Every value must be a finite number (None/NaN/±inf rejected).
- total_revenue / total_assets / total_debt must be >= 0 (negative revenue,
  assets or debt are data errors, not losses).
- net_income and roe may be any finite value (losses and negative ROE are real).
- pe_ratio must be > 0 (a zero/negative P/E is meaningless for scoring).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field


NON_NEGATIVE_METRICS = frozenset({"total_revenue", "total_assets", "total_debt"})
POSITIVE_METRICS = frozenset({"pe_ratio"})


@dataclass
class FundamentalsValidation:
    valid: dict[str, float] = field(default_factory=dict)
    rejected: list[dict] = field(default_factory=list)

    def summary(self) -> dict:
        return {
            "valid_metrics": sorted(self.valid),
            "rejected": list(self.rejected),
        }


def validate_fundamental_value(metric: str, value: float | None) -> str | None:
    """Return a rejection reason, or None when the value is usable."""
    if value is None:
        return "missing value"
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return f"non-numeric value: {value!r}"
    if not math.isfinite(value):
        return "non-finite value (NaN/inf)"
    if metric in NON_NEGATIVE_METRICS and value < 0:
        return f"impossible negative {metric}: {value}"
    if metric in POSITIVE_METRICS and value <= 0:
        return f"non-positive {metric}: {value}"
    return None


def validate_metrics(candidates: dict[str, float | None]) -> FundamentalsValidation:
    """Split candidate metric values into usable vs rejected-with-reason."""
    result = FundamentalsValidation()
    for metric, value in candidates.items():
        reason = validate_fundamental_value(metric, value)
        if reason is None:
            result.valid[metric] = float(value)  # type: ignore[arg-type]
        else:
            result.rejected.append({"metric": metric, "reason": reason})
    return result
