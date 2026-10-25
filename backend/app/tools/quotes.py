"""Quote arithmetic and freshness classification. Pure functions, no I/O."""

from datetime import datetime, timedelta

from app.schemas.market import Freshness
from app.tools.market_hours import SessionState

# A streamed or polled observation older than this during market hours is stale.
STALE_AFTER = timedelta(minutes=2)


def change_from(ltp: float | None, prev_close: float | None) -> tuple[float | None, float | None]:
    if ltp is None or prev_close is None or prev_close <= 0:
        return None, None
    change = ltp - prev_close
    return change, change / prev_close * 100.0


def classify_freshness(
    *,
    has_price: bool,
    session: SessionState,
    observed_at: datetime,
    now: datetime,
    streamed: bool,
) -> Freshness:
    if not has_price:
        return "unavailable"
    if session != "open":
        return "last_close"
    if now - observed_at > STALE_AFTER:
        return "stale"
    return "live" if streamed else "delayed"
