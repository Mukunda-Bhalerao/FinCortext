"""Market session state: exchange-reported when available, timetable otherwise."""

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from app.errors import AppError
from app.providers.base import MarketDataProvider
from app.schemas.market import MarketStatus
from app.tools.market_hours import SessionState, scheduled_state, state_from_feed, to_ist

log = logging.getLogger(__name__)

_REST_TTL = timedelta(seconds=60)


class SessionClock:
    def __init__(self, provider: MarketDataProvider):
        self._provider = provider
        self._exchange_status: str | None = None
        self._exchange_status_at: datetime | None = None
        self._lock = asyncio.Lock()

    def update_from_feed(self, segment_status: dict[str, str]) -> None:
        status = segment_status.get("NSE_EQ")
        if status:
            self._exchange_status, self._exchange_status_at = status, datetime.now(UTC)

    async def refresh(self) -> None:
        """Ask the exchange status endpoint at most once a minute; failures fall back silently."""
        now = datetime.now(UTC)
        if self._exchange_status_at and now - self._exchange_status_at < _REST_TTL:
            return
        async with self._lock:
            if self._exchange_status_at and now - self._exchange_status_at < _REST_TTL:
                return
            try:
                status = await self._provider.get_market_status("NSE")
            except AppError:
                return
            if status:
                self._exchange_status, self._exchange_status_at = status, datetime.now(UTC)

    def state(self) -> tuple[SessionState, bool]:
        """(state, from_exchange). Exchange status counts only if observed in the last 10 min."""
        now = datetime.now(UTC)
        if self._exchange_status_at and now - self._exchange_status_at < timedelta(minutes=10):
            mapped = state_from_feed(self._exchange_status)
            if mapped:
                return mapped, True
        return scheduled_state(now), False

    def status(self) -> MarketStatus:
        state, from_exchange = self.state()
        now = datetime.now(UTC)
        if state == "open":
            detail = "Regular session until 15:30 IST"
        elif state == "pre_open":
            detail = "Pre-open session, regular trading from 09:15 IST"
        else:
            local = to_ist(now)
            detail = (
                "Weekend. Next regular session Monday 09:15 IST"
                if local.weekday() >= 5
                else "Regular session 09:15 to 15:30 IST"
            )
        if not from_exchange:
            detail += " (timetable; exchange holidays not reflected)"
        return MarketStatus(
            state=state,
            basis="exchange_feed" if from_exchange else "schedule",
            detail=detail,
            as_of=self._exchange_status_at if from_exchange and self._exchange_status_at else now,
        )
