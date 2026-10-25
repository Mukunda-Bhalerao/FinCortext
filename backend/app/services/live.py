"""Live price relay.

One upstream connection to the provider's streaming feed, shared by every browser
socket. Upstream subscriptions are reference-counted so only instruments that are
on screen are requested. If the stream cannot be established, the hub falls back to
batched REST quote polling and labels updates accordingly.
"""

import asyncio
import contextlib
import logging
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from app.config import Settings
from app.errors import AppError, NotConnected, TokenInvalid
from app.providers.base import FeedEvent, LiveFeed, MarketDataProvider, Tick
from app.schemas.market import LiveStatus
from app.services.auth import AuthService
from app.services.session import SessionClock
from app.tools.quotes import change_from

log = logging.getLogger(__name__)

MAX_KEYS_PER_CLIENT = 300
STREAM_FAILURES_BEFORE_POLL = 3
STREAM_RETRY_AFTER = timedelta(minutes=5)
CLOSED_POLL_SECONDS = 60.0


@dataclass
class LatestTick:
    tick: Tick
    received_at: datetime
    transport: str


@dataclass(eq=False)
class Client:
    queue: asyncio.Queue[dict[str, Any]] = field(default_factory=lambda: asyncio.Queue(2000))
    keys: set[str] = field(default_factory=set)

    def send(self, message: dict[str, Any]) -> None:
        with contextlib.suppress(asyncio.QueueFull):
            self.queue.put_nowait(message)


def tick_message(item: LatestTick) -> dict[str, Any]:
    t = item.tick
    change, change_pct = change_from(t.ltp, t.prev_close)
    return {
        "type": "tick",
        "key": t.instrument_key,
        "ltp": t.ltp,
        "prev_close": t.prev_close,
        "change": change,
        "change_pct": change_pct,
        "last_trade_ms": t.last_trade_ms,
        "volume": t.volume_today,
        "avg_price": t.avg_price,
        "bars": [
            {
                "interval": b.interval,
                "start_ms": b.start_ms,
                "open": b.open,
                "high": b.high,
                "low": b.low,
                "close": b.close,
                "volume": b.volume,
            }
            for b in t.bars
        ],
        "transport": item.transport,
        "received_at": item.received_at.isoformat(),
    }


class LiveHub:
    def __init__(
        self,
        provider: MarketDataProvider,
        feed: LiveFeed,
        auth: AuthService,
        clock: SessionClock,
        settings: Settings,
    ):
        self._provider = provider
        self._feed = feed
        self._auth = auth
        self._clock = clock
        self._settings = settings
        self._clients: set[Client] = set()
        self._refs: Counter[str] = Counter()
        self._latest: dict[str, LatestTick] = {}
        self._wake = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._streaming = False
        self._stream_failures = 0
        self._stream_retry_at = datetime.min.replace(tzinfo=UTC)
        self._status = LiveStatus(
            transport="idle", state="not_connected", detail=None, subscribed=0, last_message_at=None
        )
        auth.on_change(self._wake.set)

    # --- lifecycle -----------------------------------------------------------------

    def start(self) -> None:
        self._task = asyncio.create_task(self._supervise(), name="live-hub")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    # --- client API --------------------------------------------------------------------

    def connect(self) -> Client:
        client = Client()
        self._clients.add(client)
        client.send(self.status_message())
        return client

    async def disconnect(self, client: Client) -> None:
        self._clients.discard(client)
        await self._release(list(client.keys))
        client.keys.clear()

    async def subscribe(self, client: Client, keys: list[str]) -> None:
        new = [k for k in dict.fromkeys(keys) if k not in client.keys]
        new = new[: max(0, MAX_KEYS_PER_CLIENT - len(client.keys))]
        client.keys.update(new)
        first = [k for k in new if self._refs[k] == 0]
        self._refs.update(new)
        for k in new:
            if k in self._latest:
                client.send(tick_message(self._latest[k]))
        if first:
            if self._streaming:
                with contextlib.suppress(Exception):
                    await self._feed.subscribe(first)
            self._wake.set()
        self._status.subscribed = len(self._refs)

    async def unsubscribe(self, client: Client, keys: list[str]) -> None:
        gone = [k for k in keys if k in client.keys]
        client.keys.difference_update(gone)
        await self._release(gone)

    async def _release(self, keys: list[str]) -> None:
        last = []
        for k in keys:
            self._refs[k] -= 1
            if self._refs[k] <= 0:
                del self._refs[k]
                last.append(k)
        if last and self._streaming:
            with contextlib.suppress(Exception):
                await self._feed.unsubscribe(last)
        self._status.subscribed = len(self._refs)

    def latest(self, key: str) -> LatestTick | None:
        return self._latest.get(key)

    def status(self) -> LiveStatus:
        return self._status.model_copy()

    def status_message(self) -> dict[str, Any]:
        market = self._clock.status()
        return {
            "type": "status",
            **self._status.model_dump(mode="json"),
            "market": market.model_dump(mode="json"),
        }

    # --- internals -----------------------------------------------------------------

    def _set_status(self, transport: str, state: str, detail: str | None = None) -> None:
        changed = (transport, state, detail) != (
            self._status.transport,
            self._status.state,
            self._status.detail,
        )
        self._status.transport = transport  # type: ignore[assignment]
        self._status.state = state  # type: ignore[assignment]
        self._status.detail = detail
        if changed:
            self._broadcast_all(self.status_message())

    def _broadcast_all(self, message: dict[str, Any]) -> None:
        for client in self._clients:
            client.send(message)

    def _publish(self, ticks: list[Tick], transport: str) -> None:
        now = datetime.now(UTC)
        self._status.last_message_at = now
        for tick in ticks:
            item = LatestTick(tick=tick, received_at=now, transport=transport)
            self._latest[tick.instrument_key] = item
            message = None
            for client in self._clients:
                if tick.instrument_key in client.keys:
                    message = message or tick_message(item)
                    client.send(message)

    async def _wait(self, seconds: float | None) -> None:
        self._wake.clear()
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self._wake.wait(), seconds)

    async def _supervise(self) -> None:
        backoff = 1.0
        while True:
            try:
                if self._auth.current_token() is None:
                    state = (
                        "unauthorized" if self._auth.status().oauth_configured else "not_connected"
                    )
                    self._set_status("idle", state, self._auth.status().problem)
                    await self._wait(None)
                    continue
                if not self._refs:
                    self._set_status("idle", "connected", None)
                    await self._wait(None)
                    continue
                now = datetime.now(UTC)
                if self._settings.live_mode == "stream" and now >= self._stream_retry_at:
                    await self._run_stream()
                    backoff = 1.0
                else:
                    await self._poll_once()
                    state, _ = self._clock.state()
                    await self._wait(
                        self._settings.poll_interval_seconds
                        if state == "open"
                        else CLOSED_POLL_SECONDS
                    )
            except asyncio.CancelledError:
                raise
            except TokenInvalid as exc:
                self._streaming = False
                if self._auth.current_token() is None:
                    continue
                # Token works for REST but the feed refused it: use polling.
                self._stream_retry_at = datetime.now(UTC) + STREAM_RETRY_AFTER
                self._set_status("poll", "connecting", exc.message)
            except Exception as exc:
                self._streaming = False
                self._stream_failures += 1
                log.warning("live stream ended: %s", type(exc).__name__)
                if self._stream_failures >= STREAM_FAILURES_BEFORE_POLL:
                    self._stream_retry_at = datetime.now(UTC) + STREAM_RETRY_AFTER
                    self._stream_failures = 0
                    self._set_status(
                        "poll", "connecting", "Streaming feed unavailable; using quote polling."
                    )
                else:
                    self._set_status("stream", "disconnected", "Reconnecting to streaming feed.")
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, 30.0)

    async def _run_stream(self) -> None:
        self._set_status("stream", "connecting", None)

        async def on_open() -> None:
            self._streaming = True
            self._stream_failures = 0
            self._set_status("stream", "connected", None)

        async def on_event(event: FeedEvent) -> None:
            if event.segment_status:
                self._clock.update_from_feed(event.segment_status)
                self._broadcast_all(self.status_message())
            if event.ticks:
                self._publish(event.ticks, "stream")

        try:
            await self._feed.run(list(self._refs), on_event, on_open)
        finally:
            self._streaming = False
        raise ConnectionError("stream closed")

    async def _poll_once(self) -> None:
        keys = list(self._refs)
        if not keys:
            return
        try:
            await self._clock.refresh()
            quotes = await self._provider.get_quotes(keys)
        except NotConnected:
            return
        except TokenInvalid:
            raise
        except AppError as exc:
            self._set_status("poll", "disconnected", exc.message)
            return
        ticks = [
            Tick(
                instrument_key=q.instrument_key,
                ltp=q.ltp,
                prev_close=q.prev_close,
                last_trade_ms=int(q.last_trade_time.timestamp() * 1000)
                if q.last_trade_time
                else None,
                volume_today=q.volume,
                avg_price=q.avg_price,
            )
            for q in quotes.values()
            if q.ltp is not None
        ]
        self._set_status("poll", "connected", "Quote polling (streaming feed not active)")
        self._publish(ticks, "poll")
