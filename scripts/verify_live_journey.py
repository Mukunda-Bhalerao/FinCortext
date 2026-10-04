"""End-phase live verification: the full user journey via the API.

Starts the backend, then exercises: stock context (curated + dynamic),
all 4 agent runs for a curated AND a dynamically searched symbol, and the
portfolio synthesis. Reads real response bodies as evidence. Never prints
secrets. Run from repo root:
    backend/.venv/Scripts/python.exe scripts/verify_live_journey.py
"""

import json
import sys
import time

import requests

sys.path.insert(0, "backend")

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

BASE = "http://127.0.0.1:8000"
CURATED = "TCS"


def wait_backend(timeout: int = 60) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        try:
            r = requests.get(f"{BASE}/health", timeout=5)
            if r.ok:
                return True
        except requests.RequestException:
            pass
        time.sleep(2)
    return False


def run_agents(symbol: str) -> bool:
    ok = True
    for agent in ("firm", "industry", "sentiment", "macro"):
        try:
            r = requests.post(f"{BASE}/api/agents/{agent}/{symbol}/run", timeout=180)
            body = r.json()
            if not r.ok:
                print(f"FAIL {agent} {symbol}: HTTP {r.status_code} {json.dumps(body)[:200]}")
                ok = False
                continue
            status = body.get("status")
            score = body.get("score")
            signal = body.get("overall_signal") or body.get("signal")
            conf = body.get("confidence")
            factors = body.get("factors") or []
            available = [f for f in factors if f.get("available")]
            evidence = sum(len(f.get("evidence") or []) for f in factors)
            rationale = (body.get("rationale") or "")[:60]
            print(
                f"OK {agent} {symbol}: status={status} score={score} signal={signal} "
                f"conf={conf} factors={len(available)}/{len(factors)} evidence={evidence}"
            )
            print(f"     rationale: {rationale}...")
            if not available:
                print(f"     NOTE: no available factors for {agent}/{symbol}")
        except Exception as exc:
            print(f"FAIL {agent} {symbol}: {type(exc).__name__}: {str(exc)[:150]}")
            ok = False
    return ok


def context(symbol: str) -> None:
    try:
        r = requests.get(f"{BASE}/api/stock/{symbol}/context", timeout=120)
        if not r.ok:
            print(f"CONTEXT FAIL {symbol}: HTTP {r.status_code}")
            return
        c = r.json()
        q = c.get("quote") or {}
        h = c.get("history") or {}
        f = c.get("fundamentals") or {}
        n = c.get("news") or {}
        print(
            f"CONTEXT {symbol}: identity={c.get('identity', {}).get('status')} "
            f"quote={q.get('status')} last={q.get('last_price')} "
            f"depth={'yes' if q.get('depth_buy') else 'no'} "
            f"history={h.get('status')}/{h.get('count')} "
            f"fundamentals={f.get('status')}/{f.get('metric_count')} "
            f"news={n.get('status')}/{n.get('count')}"
        )
    except Exception as exc:
        print(f"CONTEXT FAIL {symbol}: {type(exc).__name__}: {str(exc)[:150]}")


def main() -> int:
    if not wait_backend():
        print("Backend did not come up — start it first (uvicorn app.main:app)")
        return 2

    print("=== Stock Context ===")
    context(CURATED)

    print("=== Dynamic search + context (non-curated) ===")
    try:
        r = requests.get(f"{BASE}/api/market/search?query=ETERNAL&records=5", timeout=30)
        results = r.json().get("results") or []
        dynamic = results[0]["symbol"] if results else None
        print(f"search ETERNAL -> {dynamic}")
    except Exception as exc:
        print(f"search failed: {exc}")
        dynamic = "ETERNAL"
    if dynamic:
        context(dynamic)

    print("=== 4 agents, curated symbol ===")
    ok_curated = run_agents(CURATED)

    print("=== 4 agents, dynamic symbol ===")
    ok_dynamic = run_agents(dynamic) if dynamic else False

    print("=== Portfolio synthesis ===")
    try:
        r = requests.post(f"{BASE}/api/agents/portfolio/{CURATED}/run", timeout=180)
        body = r.json()
        if r.ok:
            persp = body.get("perspectives") or []
            print(
                f"OK portfolio: status={body.get('status')} "
                f"perspectives={len(persp)} available={body.get('agreement', {}).get('available_count')}"
            )
        else:
            print(f"FAIL portfolio: HTTP {r.status_code} {json.dumps(body)[:200]}")
    except Exception as exc:
        print(f"FAIL portfolio: {exc}")

    print(f"\nRESULT: curated={'PASS' if ok_curated else 'FAIL'} dynamic={'PASS' if ok_dynamic else 'FAIL'}")
    return 0 if (ok_curated and ok_dynamic) else 1


if __name__ == "__main__":
    raise SystemExit(main())
