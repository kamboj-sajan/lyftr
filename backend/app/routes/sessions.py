from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request

router = APIRouter()


@router.get("/sessions/{session_id}/messages")
async def session_messages(session_id: str, request: Request) -> dict[str, Any]:
    db = request.app.state.db
    if await db.get_session(session_id) is None:
        raise HTTPException(status_code=404, detail="session not found")
    return {"session_id": session_id, "messages": await db.list_messages(session_id)}
