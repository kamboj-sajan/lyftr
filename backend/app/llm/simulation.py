"""The X-Simulate-Failure test hook.

Header format: comma-separated ``<key_id>=<status>`` pairs, ``*`` meaning every
key. A specific key overrides ``*``. Malformed pairs, unknown key ids and
unsupported statuses are ignored.

A simulated failure is injected through LiteLLM itself: the attempt for that
key gets ``mock_response=<LiteLLM exception instance>``, so LiteLLM raises it
through its normal completion path and our failover loop handles it exactly
like a real provider error.
"""

from __future__ import annotations

import litellm

SIMULATED_EXCEPTIONS: dict[int, type[Exception]] = {
    429: litellm.RateLimitError,
    500: litellm.InternalServerError,
    502: litellm.BadGatewayError,
    503: litellm.ServiceUnavailableError,
}


def parse_simulation_header(value: str | None, key_ids: list[str]) -> dict[str, int]:
    """Return {key_id: status} for the keys that must fail on this request only."""
    if not value:
        return {}
    wildcard: int | None = None
    specific: dict[str, int] = {}
    for pair in value.split(","):
        key, sep, raw_status = pair.partition("=")
        key, raw_status = key.strip(), raw_status.strip()
        if not sep or not key or not raw_status.isdigit():
            continue
        status = int(raw_status)
        if status not in SIMULATED_EXCEPTIONS:
            continue
        if key == "*":
            wildcard = status
        elif key in key_ids:
            specific[key] = status

    plan: dict[str, int] = {}
    for key_id in key_ids:
        if key_id in specific:
            plan[key_id] = specific[key_id]
        elif wildcard is not None:
            plan[key_id] = wildcard
    return plan


def simulated_exception(status: int, model: str) -> Exception:
    provider = model.split("/", 1)[0] if "/" in model else "openai"
    exc_cls = SIMULATED_EXCEPTIONS[status]
    return exc_cls(message=f"Simulated {status} (X-Simulate-Failure)", llm_provider=provider, model=model)
