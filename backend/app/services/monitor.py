"""Records the latest success and failure of each external data source for the health view."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

Status = Literal["ok", "degraded", "down", "unknown"]
RECENT = timedelta(minutes=30)


@dataclass
class SourceState:
    name: str
    last_ok: datetime | None = None
    last_error: str | None = None
    last_error_at: datetime | None = None
    consecutive_failures: int = 0

    @property
    def status(self) -> Status:
        if self.last_ok is None and self.last_error_at is None:
            return "unknown"
        if self.consecutive_failures == 0:
            return "ok"
        if self.consecutive_failures >= 3 and (
            self.last_ok is None or datetime.now(UTC) - self.last_ok > RECENT
        ):
            return "down"
        return "degraded"


class SourceMonitor:
    LABELS = {
        "upstox": "Upstox market data",
        "yahoo": "Yahoo Finance fundamentals and dividends",
        "fred": "FRED macro series",
        "news": "Google News search",
        "llm": "Language model",
    }

    def __init__(self) -> None:
        self._states: dict[str, SourceState] = {}

    def _get(self, name: str) -> SourceState:
        return self._states.setdefault(name, SourceState(name))

    def ok(self, name: str) -> None:
        s = self._get(name)
        s.last_ok = datetime.now(UTC)
        s.consecutive_failures = 0

    def failed(self, name: str, message: str) -> None:
        s = self._get(name)
        s.last_error = message
        s.last_error_at = datetime.now(UTC)
        s.consecutive_failures += 1

    def states(self) -> list[SourceState]:
        return [self._get(n) for n in self.LABELS] + [
            s for n, s in self._states.items() if n not in self.LABELS
        ]
