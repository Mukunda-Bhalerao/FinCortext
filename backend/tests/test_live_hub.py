import asyncio

from app.config import Settings
from app.db import Database
from app.providers.base import FeedEvent, Tick
from app.services import live as live_module
from app.services.auth import AuthService
from app.services.live import LiveHub


class FakeClock:
    def status(self):
        from datetime import UTC, datetime

        from app.schemas.market import MarketStatus

        return MarketStatus(state="open", basis="schedule", detail="test", as_of=datetime.now(UTC))

    def update_from_feed(self, status):
        pass

    def state(self):
        return "open", None

    async def refresh(self):
        pass


class FakeFeed:
    """Opens after ``delay`` seconds, records subscriptions, emits ticks on demand."""

    def __init__(self, delay: float = 0.05, answers: set[str] | None = None):
        self.delay = delay
        self.subscribed: list[list[str]] = []
        self.answers = answers  # keys the fake provider answers; None = all
        self.on_event = None
        self.stop = asyncio.Event()

    async def run(self, initial_keys, on_event, on_open):
        await asyncio.sleep(self.delay)  # URL authorisation + handshake
        self.on_event = on_event
        await on_open()
        await self.stop.wait()

    async def subscribe(self, keys):
        self.subscribed.append(list(keys))
        answered = [k for k in keys if self.answers is None or k in self.answers]
        if self.on_event and answered:
            ticks = [
                Tick(instrument_key=k, ltp=100.0, prev_close=99.0, last_trade_ms=1, server_ms=2)
                for k in answered
            ]
            asyncio.get_running_loop().call_soon(
                lambda: asyncio.ensure_future(self.on_event(FeedEvent(ticks, {}, 2)))
            )

    async def unsubscribe(self, keys):
        pass


def _hub(feed) -> LiveHub:
    settings = Settings(_env_file=None, upstox_access_token="token")
    auth = AuthService(Database(":memory:"), settings)
    return LiveHub(None, feed, auth, FakeClock(), settings)  # type: ignore[arg-type]


def _all(feed: FakeFeed) -> set[str]:
    return {k for batch in feed.subscribed for k in batch}


def test_keys_requested_during_connection_setup_reach_the_provider():
    async def scenario():
        feed = FakeFeed(delay=0.1)
        hub = _hub(feed)
        hub.start()
        client = hub.connect()
        await hub.subscribe(client, ["A"])  # starts the connection
        await asyncio.sleep(0.02)
        await hub.subscribe(client, ["B", "C"])  # arrives mid-handshake (the old bug)
        await asyncio.sleep(0.2)
        assert {"A", "B", "C"} <= _all(feed)
        await hub.subscribe(client, ["D"])  # after open: sent immediately
        await asyncio.sleep(0.01)
        assert "D" in _all(feed)
        feed.stop.set()
        await hub.stop()

    asyncio.run(scenario())


def test_silent_keys_are_resubscribed_then_reported(monkeypatch):
    monkeypatch.setattr(live_module, "SILENT_AFTER", 0.05)
    monkeypatch.setattr(live_module, "WATCHDOG_EVERY", 0.02)

    async def scenario():
        feed = FakeFeed(delay=0.01, answers={"A"})
        hub = _hub(feed)
        hub.start()
        client = hub.connect()
        await hub.subscribe(client, ["A", "B"])
        await asyncio.sleep(0.5)
        diag = {k["key"]: k for k in hub.diagnostics()["keys"]}
        assert diag["A"]["messages"] >= 1 and not diag["A"]["silent"]
        assert diag["B"]["resubscribes"] == live_module.MAX_RESUBSCRIBES and diag["B"]["silent"]
        assert (
            sum(batch.count("B") for batch in feed.subscribed) == 1 + live_module.MAX_RESUBSCRIBES
        )
        feed.stop.set()
        await hub.stop()

    asyncio.run(scenario())


def test_out_of_order_ticks_never_move_the_price_back():
    hub = _hub(FakeFeed())
    newer = Tick(
        instrument_key="A", ltp=101.0, prev_close=100.0, last_trade_ms=2_000, server_ms=2_100
    )
    older = Tick(
        instrument_key="A", ltp=99.0, prev_close=100.0, last_trade_ms=1_000, server_ms=2_200
    )
    hub._publish([newer], "stream")
    hub._publish([older], "stream")
    assert hub.latest("A").tick.ltp == 101.0


def test_tick_buffer_keeps_changes_only_and_latency_uses_feed_time():
    hub = _hub(FakeFeed())
    hub._upstream["A"] = live_module.KeyStats(subscribed_at=0)
    for ms, px, vol in [(1_000, 10.0, 5), (1_000, 10.0, 5), (2_000, 10.5, 9), (3_000, 10.4, 12)]:
        hub._publish([Tick("A", px, 9.0, ms, vol, None, [], ms + 300)], "stream")
    assert hub.recent_ticks("A") == [(1_000, 10.0, 5), (2_000, 10.5, 9), (3_000, 10.4, 12)]
    assert hub.recent_ticks("A", since_ms=2_500) == [(3_000, 10.4, 12)]
    assert hub.latency()["provider_p50_ms"] == 300
