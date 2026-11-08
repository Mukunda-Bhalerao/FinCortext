"""Pure helpers for IPO data: parsing NSE's text fields and measuring how past issues with a
given level of demand actually listed. No I/O."""

import re
import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime

_DATE_FORMATS = ("%d-%b-%Y", "%Y-%m-%d", "%d %b %Y", "%d-%m-%Y", "%b %d, %Y")
_NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")


def parse_date(text: object) -> date | None:
    s = str(text or "").strip()
    if not s or s == "-":
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s.title() if "%b" in fmt else s, fmt).date()
        except ValueError:
            continue
    return None


def numbers(text: object) -> list[float]:
    return [float(m.replace(",", "")) for m in _NUM.findall(str(text or ""))]


def parse_price(text: object) -> float | None:
    vals = numbers(text)
    return vals[0] if vals and vals[0] > 0 else None


def parse_band(text: object) -> tuple[float | None, float | None]:
    """'Rs.78 to Rs.82' -> (78, 82); a fixed price '402' -> (402, 402)."""
    vals = [v for v in numbers(text) if v > 0][:2]
    if not vals:
        return None, None
    return min(vals), max(vals)


def parse_lot(text: object) -> int | None:
    vals = numbers(text)
    return int(vals[0]) if vals else None


def issue_period(text: object) -> tuple[date | None, date | None]:
    """'21-Oct-2026 to 23-Oct-2026' -> both dates."""
    parts = re.split(r"\s+to\s+", str(text or ""), maxsplit=1)
    if len(parts) != 2:
        return None, None
    return parse_date(parts[0]), parse_date(parts[1])


def _times(v: object) -> float | None:
    try:
        x = float(str(v).strip())
    except ValueError:
        return None
    return x if x >= 0 else None


def parse_subscription(rows: Sequence[dict]) -> dict[str, float]:
    """Times subscribed per investor category from NSE's consolidated table (all exchanges).
    Keys: qib, nii, nii_big, nii_small, retail, employee, shareholder, total."""
    out: dict[str, float] = {}
    for r in rows:
        name = str(r.get("category") or "").strip()
        times = _times(r.get("noOfTotalMeant") or r.get("noOfTime") or "")
        if times is None or not name or name == "Category":
            continue
        low = name.lower()
        if low.startswith("qualified"):
            key = "qib"
        elif low.startswith("non institutional") and "ten lakh" in low and "upto" not in low:
            key = "nii_big"
        elif low.startswith("non institutional") and "upto" in low:
            key = "nii_small"
        elif low.startswith("non institutional"):
            key = "nii"
        elif low.startswith("retail") or low.startswith("individual"):
            key = "retail"
        elif low.startswith("employee"):
            key = "employee"
        elif low.startswith("shareholder"):
            key = "shareholder"
        elif low.startswith("total"):
            key = "total"
        else:
            continue
        out.setdefault(key, times)
    return out


def parse_issue_info(rows: Sequence[dict]) -> dict[str, str]:
    """NSE lists issue facts as title/value rows; untitled rows continue the previous title."""
    out: dict[str, str] = {}
    last: str | None = None
    for r in rows:
        title = r.get("title")
        value = re.sub(r"<[^>]+>", "", str(r.get("value") or "")).strip().strip('"').strip()
        if title:
            last = str(title).strip()
            out[last] = value
        elif last and value:
            out[last] = f"{out[last]}\n{value}".strip()
    return out


# --- what happened to past issues with similar demand -------------------------------------

QIB_BUCKETS: tuple[tuple[float, float, str], ...] = (
    (0, 1, "under 1x"),
    (1, 10, "1x to 10x"),
    (10, 50, "10x to 50x"),
    (50, float("inf"), "50x or more"),
)
TOTAL_BUCKETS: tuple[tuple[float, float, str], ...] = (
    (0, 2, "under 2x"),
    (2, 10, "2x to 10x"),
    (10, 50, "10x to 50x"),
    (50, float("inf"), "50x or more"),
)
MIN_SAMPLE = 8


@dataclass(frozen=True)
class PastIssue:
    symbol: str
    listing_date: date
    qib: float | None
    total: float | None
    listing_gain: float  # listing-day open over the issue price, minus 1


@dataclass(frozen=True)
class Odds:
    measure: str  # "qib" or "total"
    bucket: str
    sample: int
    above_issue: float  # share that opened above the issue price
    average_gain: float
    median_gain: float
    worst: float
    best: float


def _bucket(value: float, buckets) -> tuple[float, float, str] | None:
    return next((b for b in buckets if b[0] <= value < b[1]), None)


def bucket_table(history: Sequence[PastIssue], measure: str) -> list[Odds]:
    buckets = QIB_BUCKETS if measure == "qib" else TOTAL_BUCKETS
    out = []
    for lo, hi, label in buckets:
        gains = [
            p.listing_gain
            for p in history
            if (v := getattr(p, measure)) is not None and lo <= v < hi
        ]
        if gains:
            out.append(
                Odds(
                    measure,
                    label,
                    len(gains),
                    sum(g > 0 for g in gains) / len(gains),
                    sum(gains) / len(gains),
                    statistics.median(gains),
                    min(gains),
                    max(gains),
                )
            )
    return out


def odds_for(history: Sequence[PastIssue], qib: float | None, total: float | None) -> Odds | None:
    """How past issues with similar demand listed. Institutional (QIB) demand is used when the
    issue has a QIB portion and enough comparable issues exist; otherwise total demand."""
    for measure, value, buckets in (("qib", qib, QIB_BUCKETS), ("total", total, TOTAL_BUCKETS)):
        if value is None:
            continue
        b = _bucket(value, buckets)
        if b is None:
            continue
        row = next((o for o in bucket_table(history, measure) if o.bucket == b[2]), None)
        if row and row.sample >= MIN_SAMPLE:
            return row
    return None


@dataclass(frozen=True)
class Mood:
    days: int
    listed: int
    above_issue_at_open: float | None
    median_listing_gain: float | None
    above_issue_now: float | None


def mood(listings: Sequence[tuple[date, float, float | None]], today: date, days: int) -> Mood:
    """listings: (listing date, listing gain, gain since issue now or None)."""
    recent = [x for x in listings if 0 <= (today - x[0]).days <= days]
    gains = [g for _, g, _ in recent]
    now = [n for _, _, n in recent if n is not None]
    return Mood(
        days,
        len(recent),
        sum(g > 0 for g in gains) / len(gains) if gains else None,
        statistics.median(gains) if gains else None,
        sum(n > 0 for n in now) / len(now) if now else None,
    )
