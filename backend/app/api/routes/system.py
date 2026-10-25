import time
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.responses import RedirectResponse

from app.api.deps import Services, services
from app.errors import AppError
from app.schemas.market import AuthStatus

router = APIRouter(prefix="/api")
Svc = Annotated[Services, Depends(services)]


STARTED_AT = datetime.now(UTC)
_RANK = {"ok": 0, "off": 0, "unknown": 0, "degraded": 1, "down": 2}


def _component(key: str, label: str, status: str, detail: str | None, **extra) -> dict:
    return {"key": key, "label": label, "status": status, "detail": detail, **extra}


def _components(svc: Services) -> list[dict]:
    out = []
    t0 = time.perf_counter()
    try:
        svc.db.fetchone("SELECT 1")
        size = svc.db.size_bytes()
        out.append(
            _component(
                "database",
                "Local database",
                "ok",
                f"{(size or 0) / 1e6:.0f} MB, answered in "
                f"{(time.perf_counter() - t0) * 1000:.0f} ms",
            )
        )
    except Exception as exc:  # report, never raise from the health check
        out.append(_component("database", "Local database", "down", type(exc).__name__))
    auth = svc.auth.status()
    out.append(
        _component(
            "upstox_auth",
            "Upstox connection",
            "ok" if auth.connected else "down",
            auth.problem
            or (
                f"Token valid until {auth.expected_expiry:%d %b %Y}"
                if auth.expected_expiry
                else None
            ),
        )
    )
    live = svc.hub.status()
    if live.state == "connected" or live.transport == "idle":
        live_status = "ok"
    elif live.state in ("connecting", "disconnected"):
        live_status = "degraded"
    else:
        live_status = "down"
    out.append(
        _component(
            "live_feed",
            "Live prices",
            live_status,
            live.detail or f"{live.state} via {live.transport}, {live.subscribed} instruments",
        )
    )
    out.append(
        _component(
            "instruments",
            "Instrument master",
            "ok" if svc.instruments.count() and not svc.instruments.last_error else "degraded",
            svc.instruments.last_error
            or f"{svc.instruments.count()} instruments, loaded {svc.instruments.loaded_on()}",
        )
    )
    for s in svc.monitor.states():
        if s.name == "llm" and svc.assistant.status().enabled is False:
            out.append(
                _component("llm", svc.monitor.LABELS["llm"], "off", "Not configured (optional)")
            )
            continue
        detail = None
        if s.consecutive_failures:
            detail = f"{s.consecutive_failures} failure(s) in a row: {s.last_error}"
        elif s.last_ok:
            detail = f"Last success {s.last_ok:%H:%M} UTC"
        else:
            detail = "Not used yet in this session"
        out.append(
            _component(
                s.name,
                svc.monitor.LABELS.get(s.name, s.name),
                s.status,
                detail,
                last_ok=s.last_ok.isoformat() if s.last_ok else None,
                last_error_at=s.last_error_at.isoformat() if s.last_error_at else None,
            )
        )
    r = svc.research.stats()
    out.append(
        _component(
            "research_worker",
            "Research engine",
            "ok"
            if r["worker_alive"] and not r["failed"]
            else ("degraded" if r["worker_alive"] else "down"),
            f"{r['queued']} queued, {r['running']} running, {r['failed']} failed"
            + (f": {r['last_error']}" if r["last_error"] else ""),
        )
    )
    state, error = svc.portfolio.status().state, svc.portfolio.state[1]
    out.append(
        _component(
            "portfolio_engine",
            "Portfolio engine",
            "degraded" if state == "failed" else "ok",
            error or state.replace("_", " "),
        )
    )
    return out


@router.get("/health")
async def health(svc: Svc) -> dict:
    components = _components(svc)
    worst = max((_RANK.get(c["status"], 0) for c in components), default=0)
    return {
        "status": "ok",
        "overall": ["ok", "degraded", "down"][worst],
        "started_at": STARTED_AT.isoformat(),
        "components": components,
        "instruments": {
            "count": svc.instruments.count(),
            "loaded_on": svc.instruments.loaded_on(),
            "error": svc.instruments.last_error,
        },
        "upstox": svc.auth.status().model_dump(mode="json"),
        "live": svc.hub.status().model_dump(mode="json"),
        "market": svc.clock.status().model_dump(mode="json"),
    }


@router.get("/auth/status")
async def auth_status(svc: Svc) -> AuthStatus:
    return svc.auth.status()


@router.get("/auth/upstox/login")
async def upstox_login(svc: Svc) -> RedirectResponse:
    return RedirectResponse(svc.auth.login_url(), status_code=302)


@router.get("/auth/upstox/callback")
async def upstox_callback(
    svc: Svc,
    code: Annotated[str | None, Query(max_length=512)] = None,
    state: Annotated[str | None, Query(max_length=128)] = None,
    error: Annotated[str | None, Query(max_length=128)] = None,
) -> RedirectResponse:
    target = svc.settings.frontend_url.rstrip("/")
    if error or not code or not state:
        return RedirectResponse(f"{target}/?upstox=error&reason=denied", status_code=302)
    try:
        await svc.auth.complete_oauth(code, state)
    except AppError as exc:
        reason = "state" if "expired" in exc.message else "exchange"
        return RedirectResponse(f"{target}/?upstox=error&reason={reason}", status_code=302)
    await svc.auth.verify(svc.provider)
    return RedirectResponse(f"{target}/?upstox=connected", status_code=302)


@router.post("/auth/upstox/disconnect")
async def upstox_disconnect(svc: Svc) -> AuthStatus:
    svc.auth.disconnect()
    return svc.auth.status()
