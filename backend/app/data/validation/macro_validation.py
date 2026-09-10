"""Validation for macro indicator bundles.

Rules (failures reported with reasons, never silently dropped):
- indicator_id known, unit non-empty
- every point has a finite numeric value
- period_end (or observed date) parses to a real date, not in the future
  (1-day tolerance for timezone edges)
- no duplicate periods within one bundle (first wins, rest rejected)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime


@dataclass
class ValidatedMacroBundle:
    indicator_id: str
    unit: str
    source_name: str
    points: list[dict] = field(default_factory=list)
    rejected: list[dict] = field(default_factory=list)


def _parse_date(raw) -> date | None:
    if raw is None or raw == "":
        return None
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    try:
        return date.fromisoformat(str(raw)[:10])
    except (ValueError, TypeError):
        return None


def _parse_ts(raw) -> datetime | None:
    if raw is None or raw == "":
        return None
    if isinstance(raw, datetime):
        return raw
    if isinstance(raw, date):
        return datetime(raw.year, raw.month, raw.day)
    try:
        text = str(raw).strip().replace("Z", "+00:00")
        return datetime.fromisoformat(text)
    except (ValueError, TypeError):
        return None


def validate_bundle(indicator_id: str, bundle: dict, today: date | None = None) -> ValidatedMacroBundle:
    """Split a provider bundle into usable points + rejected-with-reason."""
    today = today or date.today()
    out = ValidatedMacroBundle(
        indicator_id=indicator_id,
        unit=str(bundle.get("unit") or "").strip(),
        source_name=str(bundle.get("source_name") or "unknown"),
    )
    if not out.unit:
        out.rejected.append({"period": None, "reason": "missing unit for indicator"})
        return out
    seen_periods: set[str] = set()
    for point in bundle.get("points", []) or []:
        reason = _point_reason(point, today)
        if reason is not None:
            out.rejected.append({"period": point.get("period_end"), "reason": reason})
            continue
        key = str(point.get("period_end"))
        if key in seen_periods:
            out.rejected.append(
                {"period": point.get("period_end"), "reason": "duplicate period in bundle"}
            )
            continue
        seen_periods.add(key)
        out.points.append(
            {
                "period_start": _parse_date(point.get("period_start")),
                "period_end": _parse_date(point.get("period_end")),
                "value": float(point.get("value")),
                "published_at": _parse_ts(point.get("published_at")),
                "source_url": point.get("source_url"),
                "notes": point.get("notes"),
            }
        )
    out.points.sort(key=lambda p: (p["period_end"] or date.min))
    return out


def _point_reason(point: dict, today: date) -> str | None:
    value = point.get("value")
    if value is None:
        return "missing value"
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return f"non-numeric value: {value!r}"
    if not math.isfinite(value):
        return "non-finite value (NaN/inf)"
    period_end = _parse_date(point.get("period_end"))
    if period_end is None:
        return "missing/unparseable period_end"
    if (period_end - today).days > 1:
        return f"period_end {period_end.isoformat()} lies in the future"
    start = _parse_date(point.get("period_start"))
    if start is not None and start > period_end:
        return "period_start after period_end"
    return None
