"""Request and response models for the public API contract."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

MESSAGE_MAX_CHARS = 4000
SESSION_ID_MAX_CHARS = 128
SYSTEM_PROMPT_MAX_CHARS = 8000


class ChatRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=SESSION_ID_MAX_CHARS)
    message: str
    system_prompt: str | None = None

    @field_validator("session_id")
    @classmethod
    def _session_id_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("session_id must not be blank")
        return value

    @field_validator("message")
    @classmethod
    def _message_trimmed_length(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("message must not be empty")
        if len(value) > MESSAGE_MAX_CHARS:
            raise ValueError(f"message must be at most {MESSAGE_MAX_CHARS} characters")
        return value

    @field_validator("system_prompt")
    @classmethod
    def _blank_system_prompt_is_none(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        value = value.strip()
        if len(value) > SYSTEM_PROMPT_MAX_CHARS:
            raise ValueError(f"system_prompt must be at most {SYSTEM_PROMPT_MAX_CHARS} characters")
        return value


class Attempt(BaseModel):
    key_id: str
    status: int | None
    outcome: Literal["success", "error", "empty"]
    simulated: bool
    ms: int


class ChatMetadata(BaseModel):
    resolution_source: Literal["LIVE_INFERENCE", "LLM_CACHE"]
    model: str
    latency_ms: int
    input_tokens: int
    output_tokens: int
    key_id: str | None
    fallback_attempts: int
    attempts: list[Attempt] = []


class ChatResponse(BaseModel):
    session_id: str
    reply: str
    metadata: ChatMetadata
