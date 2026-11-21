# Lyftr Chat: LLM chatbot with key failover and response caching

A small full-stack chat app. A React (Vite + TypeScript) frontend talks to a FastAPI backend that calls an LLM through **LiteLLM** with a **pool of API keys** (ordered failover), an **exact-match response cache**, and **multi-turn history in SQLite**. Every reply carries metadata that shows where it came from (`LIVE_INFERENCE` or `LLM_CACHE`), which key answered, how many keys failed first, the latency and the token usage of that request.

```
Browser (React, Vercel) ──JSON──▶ FastAPI (Docker, Render) ──▶ LiteLLM ──▶ key_1 ─┐
                                   │                          │          key_2 ─┴─▶ Groq · openai/gpt-oss-120b
                                   │                          └─ in-process exact-match cache
                                   └─ SQLite /data/app.db (sessions + messages)
```

## Live URLs

| | URL |
|---|---|
| Frontend | <https://frontend-iota-eight-72.vercel.app> |
| Backend | <https://lyftr-backend.onrender.com> |
| Health | <https://lyftr-backend.onrender.com/health> |
| GitHub | <https://github.com/kamboj-sajan/lyftr> |

The backend runs on Render's free plan, which sleeps after 15 minutes without traffic. The first request after that can take up to a minute, so open `/health` first. Deployment steps: [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

## Run locally: with Docker and without

You need at least two API keys for the same provider (the app is set up for Groq). Put them in `.env`:

```bash
cp .env.example .env
# edit .env: LLM_API_KEYS=gsk_key1,gsk_key2  (comma, no spaces, no quotes)
```

For Groq, create each key in a **different organization**, because rate limits are per organization. Two keys in one organization share one quota, so real failover can't help (the simulated failover demo still works).

### With Docker (recommended)

Requires Docker and `make`.

```bash
make up        # builds both images, waits until healthy
               # frontend: http://localhost:3000   backend: http://localhost:8000/health
make logs      # follow logs
make smoke     # end-to-end smoke test against http://localhost:8000
make test      # backend tests (local venv if present, otherwise in a container)
make down      # stop; chat history is kept in the app_data volume
make clean     # stop and delete the volume (history and cache)
```

`make up` copies `.env.example` to `.env` with a warning if `.env` is missing. History survives `make down && make up` because SQLite lives on the named volume `app_data` mounted at `/data`.

### Without Docker

Requires Python 3.12 and Node.js 20.19 or newer. Start the backend from `backend/`; it reads the repo-root `.env`, and `DATABASE_URL` is overridden because `/data` only exists in the container.

```bash
cd backend
python3.12 -m venv .venv
.venv/bin/pip install --require-hashes -r requirements.txt
DATABASE_URL=sqlite:///./app.db .venv/bin/uvicorn app.main:app --port 8000 --workers 1
```

In a second terminal:

```bash
cd frontend
npm ci
VITE_API_BASE_URL=http://localhost:8000 npm run dev    # http://localhost:5173
```

Tests need no API keys; they run against a fake OpenAI-compatible server started by the test suite:

```bash
cd backend
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest          # 72 tests
```

### Project layout

```
backend/
  app/main.py          app factory: lifespan (DB, key pool, cache, warm-up), CORS, JSON-only errors
  app/config.py        settings from environment variables (pydantic-settings)
  app/schemas.py       request validation and response models
  app/db.py            SQLite storage (aiosqlite, WAL, one transaction per turn)
  app/llm/gateway.py   key pool, ordered failover loop, cache write and warm-up
  app/llm/simulation.py  X-Simulate-Failure parsing and LiteLLM exception injection
  app/routes/          /chat, /sessions/{id}/messages, /health
  tests/               pytest suite + fake OpenAI-compatible server
frontend/src/          React app (api client, chat UI, metadata chips)
scripts/smoke_test.sh  end-to-end checks against any deployment
docker-compose.yml · Makefile · render.yaml · docs/DEPLOYMENT.md
```

## Design decisions: key fallback, caching, SQLite session storage

### What happens on `POST /chat`

1. **Validate.** `message` is trimmed and must be 1–4000 characters; `session_id` must be 1–128 non-blank characters. Anything else, including malformed JSON, is FastAPI's default `422`.
2. **Lock the session.** A per-session `asyncio.Lock` stops two concurrent requests in one session from interleaving history.
3. **Build the message list.** `[system]` (request `system_prompt`, else the one stored for the session, else `DEFAULT_SYSTEM_PROMPT`) + the last `HISTORY_MAX_MESSAGES` stored messages + the new user message. The client only ever sends the new message.
4. **Call the gateway.** Ordered loop over the key pool (below).
5. **Persist on success only.** The session upsert, the user message and the assistant message (with its metadata) are written in **one transaction**, after the LLM succeeded.
6. **Respond** with `reply` and `metadata`. `latency_ms` is measured server-side with `time.perf_counter()` from the start of the handler.

### Key fallback

`LLM_API_KEYS` is parsed into an ordered pool `key_1`, `key_2`, … The app refuses to start with fewer than two keys, and logs why without printing any key.

**Why an explicit loop over `litellm.acompletion` instead of `litellm.Router` fallbacks.** The loop makes the key order deterministic, makes `fallback_attempts` exact (the number of keys that failed before one answered), and keeps failure simulation scoped to one request. The Router's retries and cooldowns are stateful across requests: a simulated failure on one request could put a key into cooldown for the next one, and the attempt count would depend on Router internals. LiteLLM still provides everything else: the provider call, normalized exception types, token usage and the cache.

Each request builds one `params` dict (`model`, `messages`, `temperature`, `max_tokens`) and reuses it unchanged for every attempt, the cache lookup and the cache write. Each attempt adds the key, `timeout=LLM_TIMEOUT_SECONDS` and `num_retries=0`, so a failing key fails over immediately instead of being retried by the provider client (verified: one provider call per failed key).

| Outcome of an attempt | What the loop does |
|---|---|
| `RateLimitError` (429, including quota exhausted) | next key |
| 5xx: `InternalServerError`, `BadGatewayError`, `ServiceUnavailableError`, `APIError` ≥ 500 | next key |
| `Timeout`, `APIConnectionError` | next key |
| `AuthenticationError`, `PermissionDeniedError`, or any 401/403 (a dead key; another may work) | next key |
| 200 with empty or whitespace-only content (never cached, never returned) | next key |
| Any other unexpected exception | next key |
| `BadRequestError` (incl. `ContextWindowExceededError`, `ContentPolicyViolationError`), `UnprocessableEntityError` | **stop**: the request itself is bad, so the other keys would fail the same way and are not burned |

When every key fails, the response is `503 {"detail": "all providers unavailable"}`. Provider error text is never passed to the client. Each attempt is logged on one line, without key values or prompts:

```
llm_attempt key_id=key_1 outcome=error status=429 simulated=true duration_ms=11 error=RateLimitError
llm_attempt key_id=key_2 outcome=success status=200 simulated=false duration_ms=689 error=-
```

### Failure simulation (`X-Simulate-Failure`)

Honored only when `ENABLE_FAILURE_SIMULATION=true`; otherwise the header is ignored completely. The format is comma-separated `<key_id>=<status>` pairs with `*` for every key, a specific key overriding `*`. Allowed statuses are 429, 500, 502 and 503; malformed pairs and unknown key ids are ignored.

The failure is **injected through LiteLLM itself**: the attempt for that key gets `mock_response=<LiteLLM exception instance>` (`RateLimitError` → 429, `InternalServerError` → 500, `BadGatewayError` → 502, `ServiceUnavailableError` → 503, all verified on the pinned version). LiteLLM raises it through its normal completion path, so it lands in exactly the same `except` branch as a real provider error. Nothing is stored between requests: no cooldowns, no circuit breakers.

**A simulated request skips the cache read** (`cache={"no-cache": True}` on each attempt). Otherwise a question that is already cached would come back as `LLM_CACHE` and the failover path would never run. Successful simulated results are still written to the cache.

### Caching

- **LiteLLM's built-in cache**, `litellm.cache = Cache(type="local")`, exact match only (no semantic caching).
- **The effective cache key is the model + the full message list** (system prompt + history + new message); `temperature` and `max_tokens` are constants from config. So the same first message in a new session is a hit, a different message never is, and a follow-up in an existing conversation has different context and is a miss. LiteLLM does not include `api_key` in the key, so a reply cached through `key_1` is also served when `key_2` would have been used.
- **A hit** is detected with `response._hidden_params["cache_hit"] is True` and returned as `LLM_CACHE` with `key_id: null`, `fallback_attempts: 0`, the identical reply and the token usage stored with the cached response.
- **Explicit cache write.** LiteLLM defers its own cache write to a background task, so an identical request sent right afterwards would miss. The gateway turns LiteLLM's write off (`cache={"no-store": True}`) and instead `await`s `litellm.cache.async_add_cache(response, **params)` with the same `params` before responding. This also guarantees that empty replies are never cached.
- **Startup warm-up.** The first cache hit after boot costs 0.3–1.2 s because LiteLLM lazily imports modules on that path, which would make the first hit look no faster than a live call. At startup the app seeds one dummy entry and reads it back; after that, hits take single-digit milliseconds (3–5 ms measured).
- **Dependencies.** That lazy import needs `orjson` and `soundfile` (and `fastapi`). Installing just these instead of the whole `litellm[proxy]` extra cut the backend image from 1.25 GB to about 790 MB. A test exercises a real cache hit so a missing module can't slip through.
- **One uvicorn worker.** The cache is in process memory; several workers would each have their own cache and give inconsistent hits. The cache is also lost on restart.

### SQLite session storage

```sql
CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id TEXT NOT NULL,
  role TEXT NOT NULL,          -- 'user' or 'assistant'
  content TEXT NOT NULL,
  metadata TEXT,               -- JSON, assistant messages only
  created_at TEXT NOT NULL     -- ISO-8601 UTC
);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, id);
CREATE TABLE IF NOT EXISTS sessions (
  session_id TEXT PRIMARY KEY, system_prompt TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
```

- The schema is created at startup. `DATABASE_URL` (`sqlite:////data/app.db` absolute, `sqlite:///./app.db` relative) is parsed to a file path and its directory created.
- WAL mode and `busy_timeout=5000`. Every operation uses its own `aiosqlite` connection, which runs `sqlite3` in a worker thread, so the event loop is never blocked.
- **Transaction-on-success:** `BEGIN IMMEDIATE` → session upsert → user message → assistant message → `COMMIT`, only after the LLM answered. A `422` or `503` writes nothing at all, so a session whose only request failed returns `404` from the history endpoint.
- A `system_prompt` sent with a request is stored on the session and used for later requests that don't send one (`COALESCE` keeps the stored prompt; blank means not provided).
- **History window:** the last `HISTORY_MAX_MESSAGES` (default 40) messages are sent to the model. If the window would start with an assistant turn, that turn is dropped.
- `GET /sessions/{id}/messages` returns the stored history oldest first, without the system prompt, with `metadata` on assistant messages only.
- In Docker the database lives on the `app_data` volume. On Render's free plan the filesystem is ephemeral (no disks on free), so history lasts while the service is awake; see [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

### Model

`LLM_MODEL=groq/openai/gpt-oss-120b`. `metadata.model` is this configured LiteLLM string; `response.model` would drop the provider prefix (Groq returns `openai/gpt-oss-120b`). `LLM_MAX_TOKENS=2048` because gpt-oss reasons before answering and those tokens count toward the limit; too low a limit can produce an empty reply, which the loop treats as a failed attempt. Switching provider only means changing `LLM_MODEL` and the keys.

### Security and supply chain

- Keys exist only in environment variables. `.env` is git-ignored and docker-ignored. Key values never appear in responses, logs, the frontend bundle or the history endpoint, and a test asserts it.
- CORS allows only `ALLOWED_ORIGINS` (whitespace and trailing slashes stripped), methods `GET, POST, OPTIONS`, headers `Content-Type` and `X-Simulate-Failure`.
- Errors are always JSON with `detail`. A catch-all returns `500 {"detail": "internal server error"}` and logs the traceback server-side only; it sits inside the CORS middleware so the browser can still read it. There are no trailing-slash routes or redirects.
- Both containers run as non-root users (`app` uid 999 for the backend, `nginx` uid 101 for the frontend). LiteLLM logging is kept at ERROR.
- **LiteLLM is pinned exactly to `1.110.2`, with hashes.** `backend/requirements.txt` is generated with `uv pip compile --generate-hashes` and installed with `pip install --require-hashes`. LiteLLM releases **1.82.7, 1.82.8 and 1.107.0** on PyPI were compromised with credential stealers; pinning an exact, checked version with hashes keeps a re-published or later bad release from being installed silently.

## Verification: how to see failover, cache hits and per-message token usage

The outputs below are from a real run against Groq (trimmed with `jq`, and `attempts` hidden where it isn't the point). Set the base URL first:

```bash
B=http://localhost:8000        # or the deployed backend URL
```

**Health**

```bash
curl -s $B/health
# {"status":"ok","keys_configured":2,"cache_enabled":true}
```

**Live inference, then a cache hit.** Same first message, two different sessions:

```bash
curl -s $B/chat -H 'Content-Type: application/json' \
  -d '{"session_id":"demo-1","message":"What is the capital of France?"}' | jq -c '{reply, metadata: (.metadata | del(.attempts))}'
# {"reply":"Paris.","metadata":{"resolution_source":"LIVE_INFERENCE","model":"groq/openai/gpt-oss-120b",
#  "latency_ms":4215,"input_tokens":96,"output_tokens":33,"key_id":"key_1","fallback_attempts":0}}

curl -s $B/chat -H 'Content-Type: application/json' \
  -d '{"session_id":"demo-2","message":"What is the capital of France?"}' | jq -c '{reply, metadata: (.metadata | del(.attempts))}'
# {"reply":"Paris.","metadata":{"resolution_source":"LLM_CACHE","model":"groq/openai/gpt-oss-120b",
#  "latency_ms":3,"input_tokens":96,"output_tokens":33,"key_id":null,"fallback_attempts":0}}
```

The second reply is identical, with the same tokens, `key_id: null` and 3 ms instead of a provider round trip. (That live call was the first one after a restart; warm live calls take about 0.5–0.9 s.)

**Failover.** `key_1` behaves as if the provider returned 429 (or 500), and `key_2` answers:

```bash
curl -s $B/chat -H 'Content-Type: application/json' -H 'X-Simulate-Failure: key_1=429' \
  -d '{"session_id":"demo-3","message":"Name one planet."}' | jq -c '{reply, key_id: .metadata.key_id, fallback_attempts: .metadata.fallback_attempts, attempts: .metadata.attempts}'
# {"reply":"Mars","key_id":"key_2","fallback_attempts":1,"attempts":[
#   {"key_id":"key_1","status":429,"outcome":"error","simulated":true,"ms":11},
#   {"key_id":"key_2","status":200,"outcome":"success","simulated":false,"ms":689}]}

curl -s $B/chat -H 'Content-Type: application/json' -H 'X-Simulate-Failure: key_1=500' \
  -d '{"session_id":"demo-4","message":"Name one ocean."}' | jq -c '.metadata | {key_id, fallback_attempts}'
# {"key_id":"key_2","fallback_attempts":1}
```

**Every key down.** 503, and nothing is written to history:

```bash
curl -s -w '  HTTP %{http_code}\n' $B/chat -H 'Content-Type: application/json' -H 'X-Simulate-Failure: *=429' \
  -d '{"session_id":"demo-5","message":"Hello?"}'
# {"detail":"all providers unavailable"}  HTTP 503

curl -s -w '  HTTP %{http_code}\n' $B/sessions/demo-5/messages
# {"detail":"session not found"}  HTTP 404
```

**Multi-turn memory and per-message token usage.** Tokens are reported per request, never as a running total:

```bash
curl -s $B/chat -H 'Content-Type: application/json' -d '{"session_id":"demo-6","message":"My favourite number is 42"}' > /dev/null
curl -s $B/chat -H 'Content-Type: application/json' -d '{"session_id":"demo-6","message":"What is my favourite number?"}' | jq -c '{reply}'
# {"reply":"Your favourite number is 42."}

curl -s $B/sessions/demo-6/messages | jq -c '.messages[] | {role, content: .content[0:30], input_tokens: .metadata.input_tokens, output_tokens: .metadata.output_tokens}'
# {"role":"user","content":"My favourite number is 42","input_tokens":null,"output_tokens":null}
# {"role":"assistant","content":"That's a classic choice! Is th","input_tokens":95,"output_tokens":58}
# {"role":"user","content":"What is my favourite number?","input_tokens":null,"output_tokens":null}
# {"role":"assistant","content":"Your favourite number is 42.","input_tokens":128,"output_tokens":48}
```

The second turn's `input_tokens` (128) include the first turn's history; its `output_tokens` (48) are only that reply's.

**Validation.** Empty, whitespace-only, over 4000 characters, a missing or 129-character `session_id`, or malformed JSON:

```bash
curl -s -w '  HTTP %{http_code}\n' $B/chat -H 'Content-Type: application/json' -d '{"session_id":"demo-7","message":"   "}'
# {"detail":[{"type":"value_error","loc":["body","message"],"msg":"Value error, message must not be empty",...}]}  HTTP 422
```

**Everything at once.** The smoke script runs 20 checks (health, live, cache, memory, history, failover, 503/404, the 422 cases, unknown session) with fresh session ids, and exits non-zero on any failure:

```bash
./scripts/smoke_test.sh $B        # All 20 checks passed
```

**Logs.** `make logs` (or the Render log view) shows one line per key attempt with `key_id`, outcome, status, `simulated` and duration, plus `llm_cache_hit` for hits.

### In the UI

- Each assistant reply has a metadata row: a **blue `LIVE_INFERENCE`** or **green `LLM_CACHE`** badge, the model, the latency (`812 ms`), `in` / `out` tokens for that message, the key that answered (`none` for cache hits), and the number of fallbacks (amber when a key failed first).
- **Cache hit:** send a message (or click a sample prompt), click **New chat**, send the same message again → green `LLM_CACHE` badge, `key none`, a few ms.
- **Multi-turn:** "My favourite number is 42" then "What is my favourite number?" in the same chat.
- **Errors:** a message over 4000 characters, or a backend that is down, shows a readable red message in the chat instead of a blank screen.
- The header shows the session id (new on every page load) and the backend status from `/health`.

## Setup Used: your editor and AI tools

> **TODO (author): fill this in before submitting.**
>
> - Editor: _…_
> - AI tools: _…_
> - How they were used: _…_

## Bonus features (if any)

- **`attempts` in the response metadata:** one entry per key tried (`key_id`, `status`, `outcome`, `simulated`, `ms`), so the failover path is visible in a single response.
- **Frontend extras:** `meta-key-id` and `meta-fallback-attempts` in every metadata row, a backend status pill (which also wakes a sleeping free-tier backend on page load), clickable sample prompts, a **New chat** button for one-click cache demos, copy buttons, light and dark themes, and a responsive layout.
- **Hardening beyond the brief:** hash-pinned Python dependencies, a smaller image (only the LiteLLM modules the cache path needs), non-root containers, CORS headers kept on 500 responses, and 401/403 treated as a dead key even when a provider wraps it as a 400.
- **Developer experience:** `make test` runs in a Docker test stage when there is no local venv; `make up` waits until the stack is healthy; the test suite ships a fake OpenAI-compatible server, so the 72 tests need no API keys.
- **Deployment as code:** a Render Blueprint (`render.yaml`) plus Vercel and Netlify configs, with click-by-click steps in [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).
