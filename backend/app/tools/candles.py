"""Candle normalization and derived statistics. Pure functions, no I/O."""

from collections.abc import Iterable, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from app.schemas.market import Candle


def parse_timestamp(value: Any) -> int:
    """Provider timestamp (ISO-8601 with offset, or epoch ms) -> Unix seconds UTC."""
    if isinstance(value, int | float):
        return int(value // 1000 if value > 10**11 else value)
    text = str(value)
    if text.isdigit():
        return parse_timestamp(int(text))
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        raise ValueError(f"timestamp without offset: {text!r}")
    return int(parsed.astimezone(UTC).timestamp())


def parse_candle_rows(rows: Iterable[Sequence[Any]]) -> list[Candle]:
    """Rows are [timestamp, open, high, low, close, volume, open_interest]; any order of rows."""
    candles: dict[int, Candle] = {}
    for row in rows:
        if len(row) < 6:
            continue
        ts = parse_timestamp(row[0])
        o, h, low, c = (float(row[i]) for i in range(1, 5))
        if min(o, h, low, c) <= 0 or h < low:
            continue
        candles[ts] = Candle(
            time=ts,
            open=o,
            high=h,
            low=low,
            close=c,
            volume=int(row[5] or 0),
            oi=float(row[6]) if len(row) > 6 and row[6] is not None else None,
        )
    return [candles[t] for t in sorted(candles)]


def merge_candles(historical: list[Candle], current: list[Candle]) -> list[Candle]:
    """Combine completed-session candles with current-session ones; current wins on overlap."""
    merged = {c.time: c for c in historical}
    merged.update({c.time: c for c in current})
    return [merged[t] for t in sorted(merged)]


def trailing_range(
    candles: list[Candle], now: datetime, days: int = 365
) -> tuple[float, float] | None:
    """(high, low) over daily candles whose start lies within the trailing window."""
    cutoff = int((now - timedelta(days=days)).timestamp())
    window = [c for c in candles if c.time >= cutoff]
    if not window:
        return None
    return max(c.high for c in window), min(c.low for c in window)
