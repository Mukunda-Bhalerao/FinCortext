"""Measure live-feed latency as a browser sees it.

Connects to the backend relay like the frontend does, subscribes to a few instruments and
records, per tick: exchange last-trade time (ltt), Upstox feed server time (when relayed),
backend receive time and client receive time. Prints percentiles of each stage and the gap
between updates per instrument.

    .venv/Scripts/python scripts/feed_probe.py [seconds] [key ...]

Stage latencies use this machine's clock against the exchange's, so they include any clock
offset; the script reports the offset it can estimate from the feed's own server timestamps.
"""

import asyncio
import json
import statistics
import sys
import time
from collections import defaultdict
from datetime import datetime

import websockets

DEFAULT_KEYS = [
    "NSE_INDEX|Nifty 50",
    "NSE_EQ|INE002A01018",  # RELIANCE
    "NSE_EQ|INE009A01021",  # INFY
    "NSE_EQ|INE040A01034",  # HDFCBANK
    "NSE_EQ|INE685A01028",  # TORNTPHARM
]


def pct(values: list[float], q: float) -> float:
    v = sorted(values)
    return v[min(len(v) - 1, int(q * (len(v) - 1)))] if v else float("nan")


def summary(name: str, values: list[float]) -> str:
    if not values:
        return f"{name:34} no samples"
    return (
        f"{name:34} n={len(values):4}  p50={pct(values, 0.5):8.0f} ms  "
        f"p90={pct(values, 0.9):8.0f} ms  max={max(values):8.0f} ms"
    )


async def main(seconds: float, keys: list[str]) -> None:
    url = "ws://127.0.0.1:8000/api/ws/live"
    exch_to_backend: list[float] = []
    backend_to_client: list[float] = []
    exch_to_client: list[float] = []
    server_to_backend: list[float] = []
    gaps: dict[str, list[float]] = defaultdict(list)
    last_seen: dict[str, float] = {}
    last_ltt: dict[str, int] = {}
    transports: dict[str, int] = defaultdict(int)
    repeats = 0
    async with websockets.connect(url, origin="http://localhost:5173") as ws:
        await ws.send(json.dumps({"action": "subscribe", "keys": keys}))
        end = time.time() + seconds
        while time.time() < end:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=max(0.1, end - time.time()))
            except TimeoutError:
                break
            now_ms = time.time() * 1000
            msg = json.loads(raw)
            if msg.get("type") != "tick":
                continue
            key = msg["key"]
            transports[msg.get("transport", "?")] += 1
            recv_ms = datetime.fromisoformat(msg["received_at"]).timestamp() * 1000
            ltt = msg.get("last_trade_ms")
            if ltt:
                if last_ltt.get(key) == ltt:
                    repeats += 1
                last_ltt[key] = ltt
                exch_to_backend.append(recv_ms - ltt)
                exch_to_client.append(now_ms - ltt)
            if msg.get("server_ms"):
                server_to_backend.append(recv_ms - msg["server_ms"])
            backend_to_client.append(now_ms - recv_ms)
            if key in last_seen:
                gaps[key].append(now_ms - last_seen[key])
            last_seen[key] = now_ms
    print(f"window {seconds:.0f}s, transports {dict(transports)}, repeated ltt {repeats}")
    print(summary("exchange trade -> backend receive", exch_to_backend))
    print(summary("feed server time -> backend receive", server_to_backend))
    print(summary("backend receive -> client receive", backend_to_client))
    print(summary("exchange trade -> client receive", exch_to_client))
    if server_to_backend:
        offset = min(server_to_backend)
        print(f"clock offset estimate (this machine vs feed server): {offset:.0f} ms")
        corrected = [x - offset for x in exch_to_client]
        print(summary("exchange trade -> client (offset-corrected)", corrected))
    for key, g in gaps.items():
        print(
            f"  gap between updates {key:28} n={len(g):4}  median={statistics.median(g):7.0f} ms  "
            f"max={max(g):7.0f} ms"
        )


if __name__ == "__main__":
    secs = float(sys.argv[1]) if len(sys.argv) > 1 else 60
    asyncio.run(main(secs, sys.argv[2:] or DEFAULT_KEYS))
