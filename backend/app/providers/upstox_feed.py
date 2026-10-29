"""Upstox Market Data Feed V3 (WebSocket, protobuf).

Per the official documentation and SDK: obtain an authorized wss URL from
/v3/feed/market-data-feed/authorize, then send subscription requests as JSON
encoded in *binary* frames: {"guid", "method": "sub"|"unsub"|"change_mode",
"data": {"mode", "instrumentKeys"}}. Responses are ``FeedResponse`` protobuf
messages (MarketDataFeed.proto, v3).
"""

import json
import logging
import uuid
from collections.abc import Awaitable, Callable

import websockets
from google.protobuf.message import DecodeError
from websockets.exceptions import InvalidStatus

from app.errors import TokenInvalid
from app.providers.base import FeedEvent, OHLCBar, Tick
from app.providers.upstox import UpstoxProvider
from app.providers.upstox_proto import MarketDataFeed_pb2 as pb

log = logging.getLogger(__name__)

MODE = "full"  # LTPC + OHLC bars + day volume; documented limit 2000 keys per connection
SUB_CHUNK = 100  # keys per subscription request


def _bars(market_ohlc: "pb.MarketOHLC") -> list[OHLCBar]:
    return [
        OHLCBar(
            interval=b.interval,
            open=b.open,
            high=b.high,
            low=b.low,
            close=b.close,
            volume=int(b.vol),
            start_ms=int(b.ts),
        )
        for b in market_ohlc.ohlc
        if b.open > 0 and b.high >= b.low
    ]


def decode_feed_message(raw: bytes) -> FeedEvent:
    msg = pb.FeedResponse.FromString(raw)
    server_ms = int(msg.currentTs) or None
    ticks: list[Tick] = []
    for key, feed in msg.feeds.items():
        kind = feed.WhichOneof("FeedUnion")
        ltpc = None
        volume = None
        avg = None
        bars: list[OHLCBar] = []
        if kind == "ltpc":
            ltpc = feed.ltpc
        elif kind == "fullFeed":
            inner = feed.fullFeed.WhichOneof("FullFeedUnion")
            if inner == "marketFF":
                mff = feed.fullFeed.marketFF
                ltpc, volume, avg = mff.ltpc, int(mff.vtt) or None, mff.atp or None
                bars = _bars(mff.marketOHLC)
            elif inner == "indexFF":
                iff = feed.fullFeed.indexFF
                ltpc = iff.ltpc
                bars = _bars(iff.marketOHLC)
        elif kind == "firstLevelWithGreeks":
            ltpc, volume = (
                feed.firstLevelWithGreeks.ltpc,
                int(feed.firstLevelWithGreeks.vtt) or None,
            )
        if ltpc is None or ltpc.ltp <= 0:
            continue
        ticks.append(
            Tick(
                instrument_key=key,
                ltp=ltpc.ltp,
                prev_close=ltpc.cp if ltpc.cp > 0 else None,
                last_trade_ms=int(ltpc.ltt) or None,
                volume_today=volume,
                avg_price=avg,
                bars=bars,
                server_ms=server_ms,
            )
        )
    status = {
        seg: pb.MarketStatus.Name(value) for seg, value in msg.marketInfo.segmentStatus.items()
    }
    return FeedEvent(ticks=ticks, segment_status=status, server_ms=server_ms)


def _request(method: str, keys: list[str]) -> bytes:
    payload = {"guid": uuid.uuid4().hex, "method": method, "data": {"instrumentKeys": keys}}
    if method == "sub":
        payload["data"]["mode"] = MODE
    return json.dumps(payload).encode()


class UpstoxFeed:
    def __init__(self, provider: UpstoxProvider):
        self._provider = provider
        self._ws: websockets.ClientConnection | None = None

    async def run(
        self,
        initial_keys: list[str],
        on_event: Callable[[FeedEvent], Awaitable[None]],
        on_open: Callable[[], Awaitable[None]],
    ) -> None:
        url = await self._provider.get_feed_url()
        try:
            async with websockets.connect(
                url, open_timeout=10, ping_interval=20, ping_timeout=20, max_size=2**22
            ) as ws:
                self._ws = ws
                if initial_keys:
                    await self.subscribe(initial_keys)
                # The hub subscribes everything it needs at this point, after the socket is
                # open, so keys requested while the connection was being set up are not lost.
                await on_open()
                async for raw in ws:
                    if not isinstance(raw, bytes):
                        continue
                    try:
                        event = decode_feed_message(raw)
                    except DecodeError:
                        log.warning("undecodable feed frame (%d bytes)", len(raw))
                        continue
                    await on_event(event)
        except InvalidStatus as exc:
            if exc.response.status_code in (401, 403):
                raise TokenInvalid("Upstox refused the market data feed for this token.") from exc
            raise
        finally:
            self._ws = None

    async def subscribe(self, keys: list[str]) -> None:
        if self._ws is not None:
            for i in range(0, len(keys), SUB_CHUNK):
                await self._ws.send(_request("sub", keys[i : i + SUB_CHUNK]))

    async def unsubscribe(self, keys: list[str]) -> None:
        if self._ws is not None:
            for i in range(0, len(keys), SUB_CHUNK):
                await self._ws.send(_request("unsub", keys[i : i + SUB_CHUNK]))
