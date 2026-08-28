"""Validation for market OHLCV data.

Invalid rows are never silently discarded: they are collected with reasons and
reported to the caller, which logs/records them as provenance.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.domain.models.market import MarketPrice, validate_price_consistency


@dataclass
class ValidationResult:
    valid: list[MarketPrice] = field(default_factory=list)
    rejected: list[dict] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.valid)

    def summary(self) -> dict:
        return {
            "valid_count": len(self.valid),
            "rejected_count": len(self.rejected),
            "rejections": self.rejected[:20],
        }


def validate_market_bars(bars: list[MarketPrice]) -> ValidationResult:
    """Validate a list of canonical bars.

    Checks:
    - required fields present (enforced by the Pydantic model itself)
    - positive prices, non-negative volume (model validators)
    - high >= low, open/close within [low, high]
    - no duplicate (symbol, trade_date) rows — first occurrence wins
    - date ordering is not required within the list (provider order varies),
      duplicates are the ordering-sensitive failure mode we guard against.
    """
    result = ValidationResult()
    seen_dates: set = set()

    for bar in bars:
        problems = validate_price_consistency(bar)
        if bar.trade_date in seen_dates:
            problems.append("duplicate trade_date for symbol")
        if problems:
            result.rejected.append(
                {
                    "symbol": bar.symbol,
                    "trade_date": str(bar.trade_date),
                    "reasons": problems,
                }
            )
            continue
        seen_dates.add(bar.trade_date)
        result.valid.append(bar)

    return result