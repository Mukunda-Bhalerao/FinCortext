"""Health and system status endpoints."""

from __future__ import annotations

from fastapi import APIRouter

from app.core.config import settings

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict:
    """Liveness + basic configuration status (no secrets exposed)."""
    return {
        "status": "ok",
        "service": "fincortext-backend",
        "version": "0.1.0",
        "config": settings.summary(),
    }