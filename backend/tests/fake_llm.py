"""A tiny OpenAI-compatible chat completions server for tests.

It runs in a background thread and answers ``POST /v1/chat/completions``.
The HTTP status is chosen from the bearer token so that *real* (non-simulated)
provider failures can be exercised:

    key contains "rate"   -> 429
    key contains "boom"   -> 500
    key contains "unavail"-> 503
    key contains "dead"   -> 401
    key contains "badreq" -> 400 (a request-caused error)
    key contains "empty"  -> 200 with empty content
    anything else         -> 200 with "Fake reply to: <last user message>"

When the last user message is a question and earlier user turns exist, the
reply also quotes the previous user turn, a crude stand-in for memory.

Every request body is recorded (together with the key that sent it) so tests
can inspect exactly what was sent to the provider.
"""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class FakeLLMServer:
    def __init__(self, delay_seconds: float = 0.3) -> None:
        self.delay_seconds = delay_seconds
        self.requests: list[dict] = []
        self._lock = threading.Lock()
        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), self._handler_class())
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)

    @property
    def port(self) -> int:
        return self._httpd.server_address[1]

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}/v1"

    def start(self) -> "FakeLLMServer":
        self._thread.start()
        return self

    def stop(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()

    def reset(self) -> None:
        with self._lock:
            self.requests.clear()

    def calls_for(self, key: str) -> list[dict]:
        with self._lock:
            return [r for r in self.requests if r["api_key"] == key]

    # -- request handling -------------------------------------------------

    def _record(self, api_key: str, body: dict) -> None:
        with self._lock:
            self.requests.append({"api_key": api_key, "body": body})

    def _handler_class(self):
        server = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args) -> None:  # keep test output quiet
                pass

            def _send(self, status: int, payload: dict) -> None:
                data = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}")
                auth = self.headers.get("Authorization", "")
                api_key = auth.removeprefix("Bearer ").strip()
                server._record(api_key, body)

                if not self.path.endswith("/chat/completions"):
                    self._send(404, {"error": {"message": "not found"}})
                    return

                time.sleep(server.delay_seconds)

                for marker, status in (
                    ("rate", 429),
                    ("boom", 500),
                    ("unavail", 503),
                    ("dead", 401),
                    ("badreq", 400),
                ):
                    if marker in api_key:
                        self._send(status, {"error": {"message": f"fake {status}", "code": status}})
                        return

                messages = body.get("messages", [])
                user_turns = [str(m.get("content", "")) for m in messages if m.get("role") == "user"]
                last_user = user_turns[-1] if user_turns else ""
                content = "" if "empty" in api_key else f"Fake reply to: {last_user}"
                # Crude "memory": a question in a conversation quotes the previous user turn,
                # so multi-turn checks (e.g. "What is my favourite number?") can pass.
                if content and last_user.rstrip().endswith("?") and len(user_turns) > 1:
                    content += f" (you said earlier: {user_turns[-2]})"
                prompt_chars = sum(len(str(m.get("content", ""))) for m in messages)
                usage = {
                    "prompt_tokens": max(1, prompt_chars // 4),
                    "completion_tokens": len(content.split()),
                }
                usage["total_tokens"] = usage["prompt_tokens"] + usage["completion_tokens"]
                self._send(
                    200,
                    {
                        "id": f"chatcmpl-fake-{len(server.requests)}",
                        "object": "chat.completion",
                        "created": int(time.time()),
                        "model": body.get("model", "fake-model"),
                        "choices": [
                            {
                                "index": 0,
                                "message": {"role": "assistant", "content": content},
                                "finish_reason": "stop",
                            }
                        ],
                        "usage": usage,
                    },
                )

        return Handler
