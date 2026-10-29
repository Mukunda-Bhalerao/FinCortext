"""Browser socket: {"action": "subscribe"|"unsubscribe", "keys": [...]} in, ticks/status out."""

import asyncio
import contextlib
import json
from typing import Annotated

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect

from app.api.deps import Services, services, ws_services

router = APIRouter()
Svc = Annotated[Services, Depends(services)]


@router.get("/api/live/diagnostics")
async def diagnostics(svc: Svc) -> dict:
    """Per-key upstream state, silent keys and measured feed latency."""
    return svc.hub.diagnostics()


@router.get("/api/live/ticks")
async def ticks(
    svc: Svc,
    key: Annotated[str, Query(max_length=64)],
    since_ms: Annotated[int, Query(ge=0)] = 0,
) -> dict:
    """Streamed updates recorded for a subscribed instrument, for seconds-based candles.

    Each row is [exchange trade time ms, price, cumulative day volume]. Only updates received
    since the instrument was first subscribed exist; there is no earlier tick history.
    """
    svc.instruments.get(key)
    rows = svc.hub.recent_ticks(key, since_ms)
    return {"key": key, "ticks": rows, "count": len(rows)}


@router.websocket("/api/ws/live")
async def live(websocket: WebSocket) -> None:
    svc = ws_services(websocket)
    origin = websocket.headers.get("origin")
    if origin and origin.rstrip("/") not in svc.settings.allowed_origins:
        await websocket.close(code=1008)
        return
    await websocket.accept()
    client = svc.hub.connect()

    async def pump() -> None:
        while True:
            await websocket.send_json(await client.queue.get())

    sender = asyncio.create_task(pump())
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
                action = msg.get("action")
                keys = [k for k in msg.get("keys", []) if isinstance(k, str) and len(k) < 64]
            except (ValueError, AttributeError):
                continue
            if action in ("subscribe", "unsubscribe"):
                known = set(svc.instruments.get_many(keys))
                valid = [k for k in keys if k in known]
                if action == "subscribe":
                    await svc.hub.subscribe(client, valid)
                else:
                    await svc.hub.unsubscribe(client, valid)
    except WebSocketDisconnect:
        pass
    finally:
        sender.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await sender
        await svc.hub.disconnect(client)
