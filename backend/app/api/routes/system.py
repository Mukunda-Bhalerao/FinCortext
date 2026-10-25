from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.responses import RedirectResponse

from app.api.deps import Services, services
from app.errors import AppError
from app.schemas.market import AuthStatus

router = APIRouter(prefix="/api")
Svc = Annotated[Services, Depends(services)]


@router.get("/health")
async def health(svc: Svc) -> dict:
    return {
        "status": "ok",
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
