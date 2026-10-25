"""NSE equity session rules. Pure functions, no I/O."""

from datetime import UTC, datetime, time, timedelta, timezone
from typing import Literal

# India has no daylight saving; a fixed offset avoids depending on the OS tz database.
IST = timezone(timedelta(hours=5, minutes=30), "IST")

PRE_OPEN_START = time(9, 0)
SESSION_OPEN = time(9, 15)
SESSION_CLOSE = time(15, 30)

SessionState = Literal["open", "pre_open", "closed"]

# Values of the MarketStatus enum in Upstox MarketDataFeed.proto
_FEED_STATUS: dict[str, SessionState] = {
    "PRE_OPEN_START": "pre_open",
    "PRE_OPEN_END": "pre_open",
    "NORMAL_OPEN": "open",
    "NORMAL_CLOSE": "closed",
    "CLOSING_START": "closed",
    "CLOSING_END": "closed",
}


def to_ist(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(IST)


def scheduled_state(moment: datetime) -> SessionState:
    """Session state from the regular weekday timetable (exchange holidays not known)."""
    local = to_ist(moment)
    if local.weekday() >= 5:
        return "closed"
    t = local.time()
    if PRE_OPEN_START <= t < SESSION_OPEN:
        return "pre_open"
    if SESSION_OPEN <= t < SESSION_CLOSE:
        return "open"
    return "closed"


def state_from_feed(segment_status: str | None) -> SessionState | None:
    if segment_status is None:
        return None
    return _FEED_STATUS.get(segment_status)


def session_date(moment: datetime) -> datetime:
    """IST calendar date of ``moment`` at midnight IST."""
    local = to_ist(moment)
    return local.replace(hour=0, minute=0, second=0, microsecond=0)
