from __future__ import annotations

import asyncio
import time
import weakref

from fastapi import APIRouter, Header, HTTPException, Request

from app.llm.gateway import AllProvidersUnavailable
from app.llm.simulation import parse_simulation_header
from app.schemas import ChatRequest, ChatResponse

router = APIRouter()

ALL_PROVIDERS_UNAVAILABLE = "all providers unavailable"


class SessionLocks:
    """One asyncio.Lock per session so concurrent requests can't interleave history.

    A WeakValueDictionary drops a lock as soon as no request is holding it.
    """

    def __init__(self) -> None:
        self._locks: weakref.WeakValueDictionary[str, asyncio.Lock] = weakref.WeakValueDictionary()

    def get(self, session_id: str) -> asyncio.Lock:
        lock = self._locks.get(session_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[session_id] = lock
        return lock


@router.post("/chat", response_model=ChatResponse)
async def chat(
    body: ChatRequest,
    request: Request,
    x_simulate_failure: str | None = Header(default=None),
) -> ChatResponse:
    started = time.perf_counter()
    state = request.app.state
    settings, db, gateway = state.settings, state.db, state.gateway

    simulation = (
        parse_simulation_header(x_simulate_failure, gateway.key_ids) if settings.enable_failure_simulation else {}
    )

    lock = state.session_locks.get(body.session_id)
    async with lock:
        session = await db.get_session(body.session_id)
        system_prompt = (
            body.system_prompt
            or (session["system_prompt"] if session else None)
            or settings.default_system_prompt
        )
        history = await db.recent_messages(body.session_id, settings.history_max_messages)
        # A truncated window must not start with an orphaned assistant turn.
        while history and history[0]["role"] != "user":
            history.pop(0)
        messages = [{"role": "system", "content": system_prompt}, *history, {"role": "user", "content": body.message}]

        try:
            result = await gateway.complete(messages, simulation)
        except AllProvidersUnavailable:
            raise HTTPException(status_code=503, detail=ALL_PROVIDERS_UNAVAILABLE) from None

        metadata = {
            "resolution_source": "LLM_CACHE" if result.cache_hit else "LIVE_INFERENCE",
            "model": gateway.model,  # the LiteLLM model string we called, not response.model
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
            "key_id": result.key_id,
            "fallback_attempts": result.fallback_attempts,
            "attempts": result.attempts,
        }
        await db.save_turn(body.session_id, body.system_prompt, body.message, result.reply, metadata)

    return ChatResponse(session_id=body.session_id, reply=result.reply, metadata=metadata)
