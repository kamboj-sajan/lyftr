"""LiteLLM gateway: ordered key pool, explicit failover loop and exact-match caching.

Why an explicit loop instead of litellm.Router fallbacks: the loop gives a
deterministic key order, an exact ``fallback_attempts`` count, and failure
simulation that is scoped to one request. Router cooldowns would carry state
from one request (including simulated failures) into the next.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

import litellm
from litellm import Cache
from litellm.types.utils import ModelResponse, Usage

from app.config import Settings
from app.llm.simulation import simulated_exception

logger = logging.getLogger("app.llm")

WARMUP_MODEL = "openai/warmup"


class AllProvidersUnavailable(Exception):
    """Every key failed (or the request itself was rejected by the provider)."""


@dataclass(frozen=True)
class KeySlot:
    key_id: str
    api_key: str = field(repr=False)  # never printed, never logged


@dataclass
class CompletionResult:
    reply: str
    cache_hit: bool
    input_tokens: int
    output_tokens: int
    key_id: str | None
    fallback_attempts: int
    attempts: list[dict[str, Any]]


def _status_of(exc: BaseException) -> int | None:
    status = getattr(exc, "status_code", None)
    return status if isinstance(status, int) else None


def is_request_error(exc: BaseException) -> bool:
    """A 4xx caused by the request itself: every other key would fail the same way.

    BadRequestError covers ContextWindowExceededError and ContentPolicyViolationError
    (both subclass it). A 401/403 wrapped as BadRequestError is a dead key, not a bad
    request, so it still fails over.
    """
    if isinstance(exc, (litellm.BadRequestError, litellm.UnprocessableEntityError)):
        return _status_of(exc) not in (401, 403)
    return False


def _reply_text(response: Any) -> str:
    try:
        content = response.choices[0].message.content
    except (AttributeError, IndexError, TypeError):
        return ""
    return content if isinstance(content, str) else ""


def _usage(response: Any) -> tuple[int, int]:
    usage = getattr(response, "usage", None)
    prompt = getattr(usage, "prompt_tokens", 0) or 0
    completion = getattr(usage, "completion_tokens", 0) or 0
    return int(prompt), int(completion)


class LLMGateway:
    def __init__(self, settings: Settings) -> None:
        keys = settings.api_keys
        if len(keys) < 2:
            raise ValueError(f"LLM_API_KEYS must contain at least 2 comma-separated keys (found {len(keys)})")
        self.slots = [KeySlot(f"key_{i}", key) for i, key in enumerate(keys, start=1)]
        self.model = settings.llm_model
        self.api_base = settings.llm_api_base
        self.timeout = settings.llm_timeout_seconds
        self.temperature = settings.llm_temperature
        self.max_tokens = settings.llm_max_tokens
        self.cache_type = settings.cache_type
        self.cache_dir = settings.cache_dir

    @property
    def key_ids(self) -> list[str]:
        return [slot.key_id for slot in self.slots]

    @property
    def cache_enabled(self) -> bool:
        return litellm.cache is not None

    # -- cache ------------------------------------------------------------

    def setup_cache(self) -> None:
        if self.cache_type != "local":
            raise ValueError(f"Unsupported CACHE_TYPE {self.cache_type!r}")
        litellm.cache = Cache(type="local")

    async def warm_up(self) -> None:
        """Pay LiteLLM's lazy-import cost for the cache-hit path at startup.

        Without this the first real cache hit after boot takes hundreds of ms and
        looks no faster than a live call. We seed one dummy entry and read it back.
        """
        if litellm.cache is None:
            return
        params = {
            "model": WARMUP_MODEL,
            "messages": [{"role": "user", "content": "__warmup__"}],
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        dummy = ModelResponse(
            model=WARMUP_MODEL,
            choices=[{"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
            usage=Usage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
        )
        started = time.perf_counter()
        try:
            litellm.cache.add_cache(dummy, **params)
            # mock_response is only a safety net: on a hit LiteLLM returns before using it.
            response = await litellm.acompletion(
                **params, api_key="warmup", caching=True, num_retries=0, cache={"no-store": True}, mock_response="ok"
            )
            hit = response._hidden_params.get("cache_hit") is True
            logger.info("cache warm-up done hit=%s duration_ms=%d", hit, (time.perf_counter() - started) * 1000)
        except Exception as exc:  # warm-up must never stop the app from booting
            logger.warning("cache warm-up failed: %s", type(exc).__name__)

    # -- completion -------------------------------------------------------

    async def complete(self, messages: list[dict[str, str]], simulation: dict[str, int]) -> CompletionResult:
        """Try each key in order until one returns a non-empty reply.

        ``simulation`` maps key_id -> HTTP status to fake for THIS request only.
        """
        # One params dict per request, reused unchanged for every attempt, the
        # cache lookup and the cache write, so the cache key is model + messages.
        params: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        # A simulated request skips the cache READ so the failover path always runs.
        # LiteLLM's own (deferred) cache write is disabled with no-store; we write
        # explicitly below, only for non-empty successful replies.
        cache_control = {"no-store": True}
        if simulation:
            cache_control["no-cache"] = True

        attempts: list[dict[str, Any]] = []
        for slot in self.slots:
            simulated_status = simulation.get(slot.key_id)
            call: dict[str, Any] = {
                **params,
                "api_key": slot.api_key,
                "timeout": self.timeout,
                "num_retries": 0,
                "caching": self.cache_enabled,
                "cache": cache_control,
            }
            if self.api_base:
                call["api_base"] = self.api_base
            if simulated_status is not None:
                call["mock_response"] = simulated_exception(simulated_status, self.model)

            started = time.perf_counter()
            try:
                response = await litellm.acompletion(**call)
            except Exception as exc:
                elapsed = int((time.perf_counter() - started) * 1000)
                status = _status_of(exc)
                attempts.append(self._attempt(slot, "error", status, simulated_status is not None, elapsed, exc))
                if is_request_error(exc):
                    # Request-caused 4xx: other keys would fail too, so don't burn them.
                    raise AllProvidersUnavailable() from None
                continue

            elapsed = int((time.perf_counter() - started) * 1000)
            reply = _reply_text(response)
            if not reply.strip():
                attempts.append(self._attempt(slot, "empty", 200, simulated_status is not None, elapsed))
                continue

            input_tokens, output_tokens = _usage(response)
            if response._hidden_params.get("cache_hit") is True:
                logger.info("llm_cache_hit duration_ms=%d", elapsed)
                return CompletionResult(reply, True, input_tokens, output_tokens, None, 0, [])

            attempts.append(self._attempt(slot, "success", 200, False, elapsed))
            await self._write_cache(response, params)
            return CompletionResult(
                reply=reply,
                cache_hit=False,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                key_id=slot.key_id,
                fallback_attempts=len(attempts) - 1,
                attempts=attempts,
            )

        raise AllProvidersUnavailable()

    async def _write_cache(self, response: Any, params: dict[str, Any]) -> None:
        # LiteLLM defers its own cache write to a background task, so an identical
        # request sent immediately afterwards would miss. Write it now, with the
        # exact same params, before the response goes back to the client.
        if litellm.cache is None:
            return
        try:
            await litellm.cache.async_add_cache(response, **params)
        except Exception as exc:
            logger.warning("cache write failed: %s", type(exc).__name__)

    @staticmethod
    def _attempt(
        slot: KeySlot, outcome: str, status: int | None, simulated: bool, ms: int, exc: BaseException | None = None
    ) -> dict[str, Any]:
        logger.info(
            "llm_attempt key_id=%s outcome=%s status=%s simulated=%s duration_ms=%d error=%s",
            slot.key_id,
            outcome,
            status,
            str(simulated).lower(),
            ms,
            type(exc).__name__ if exc else "-",
        )
        return {"key_id": slot.key_id, "status": status, "outcome": outcome, "simulated": simulated, "ms": ms}
