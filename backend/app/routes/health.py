from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter()


@router.get("/health")
async def health(request: Request) -> Any:
    state = request.app.state
    gateway = getattr(state, "gateway", None)
    db = getattr(state, "db", None)
    if gateway is None or db is None:
        return JSONResponse(status_code=503, content={"detail": "starting up"})
    if not await db.ping():
        return JSONResponse(status_code=503, content={"detail": "database unavailable"})
    return {
        "status": "ok",
        "keys_configured": len(gateway.slots),
        "cache_enabled": gateway.cache_enabled,
    }
