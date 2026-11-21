#!/usr/bin/env bash
# End-to-end smoke test for the chat API.
#
#   ./scripts/smoke_test.sh [BASE_URL]        (default: $BASE_URL or http://localhost:8000)
#
# Needs bash, curl and jq. Prints PASS/FAIL per check and exits non-zero if any check fails.
# The failover checks need ENABLE_FAILURE_SIMULATION=true on the server.
# Every run uses fresh session ids and a unique message, so earlier runs never pre-warm the cache.
# About 6 real LLM calls are made per run.

set -uo pipefail

BASE_URL="${1:-${BASE_URL:-http://localhost:8000}}"
BASE_URL="${BASE_URL%/}"
TIMEOUT="${SMOKE_TIMEOUT:-90}"          # seconds per request
WAIT_FOR_HEALTH="${SMOKE_WAIT:-120}"    # free hosts can take a while to wake up

for tool in curl jq; do
  command -v "$tool" >/dev/null 2>&1 || { echo "error: '$tool' is required" >&2; exit 2; }
done

if [ -t 1 ]; then GREEN=$'\e[32m'; RED=$'\e[31m'; DIM=$'\e[2m'; BOLD=$'\e[1m'; RESET=$'\e[0m'
else GREEN=""; RED=""; DIM=""; BOLD=""; RESET=""; fi

PASSED=0
FAILED=0
STATUS=""
BODY=""
BODY_FILE="$(mktemp)"
trap 'rm -f "$BODY_FILE"' EXIT

pass() { PASSED=$((PASSED + 1)); echo "${GREEN}PASS${RESET} $1"; }
fail() {
  FAILED=$((FAILED + 1))
  echo "${RED}FAIL${RESET} $1"
  echo "${DIM}     status=${STATUS} body=$(printf '%s' "$BODY" | head -c 400)${RESET}"
  if [ -n "${2:-}" ]; then echo "${DIM}     hint: $2${RESET}"; fi
}

# request METHOD PATH [JSON_BODY] [EXTRA_HEADER] -> sets STATUS and BODY
request() {
  local method="$1" path="$2" data="${3:-}" header="${4:-}"
  local args=(-sS -o "$BODY_FILE" -w '%{http_code}' --max-time "$TIMEOUT" -X "$method")
  if [ -n "$data" ]; then args+=(-H 'Content-Type: application/json' --data-binary "$data"); fi
  if [ -n "$header" ]; then args+=(-H "$header"); fi
  STATUS="$(curl "${args[@]}" "$BASE_URL$path" 2>/dev/null)" || STATUS="000"
  BODY="$(cat "$BODY_FILE" 2>/dev/null || true)"
}

# chat SESSION_ID MESSAGE [EXTRA_HEADER]
chat() {
  request POST /chat "$(jq -nc --arg s "$1" --arg m "$2" '{session_id: $s, message: $m}')" "${3:-}"
}

# body_matches JQ_FILTER [jq args...] -> true if the filter evaluates to true on BODY
body_matches() {
  local filter="$1"; shift
  printf '%s' "$BODY" | jq -e "$@" "$filter" >/dev/null 2>&1
}

# expect NAME EXPECTED_STATUS JQ_FILTER [jq args...]
expect() {
  local name="$1" want="$2" filter="$3"; shift 3
  if [ "$STATUS" = "$want" ] && body_matches "$filter" "$@"; then pass "$name"; else fail "$name" "${HINT:-}"; fi
  HINT=""
}

RUN_ID="$(date +%s)-$RANDOM$RANDOM"
SID_LIVE="smoke-$RUN_ID-live"
SID_CACHE="smoke-$RUN_ID-cache"
SID_OTHER="smoke-$RUN_ID-other"
SID_MEMORY="smoke-$RUN_ID-memory"
SID_FAIL_429="smoke-$RUN_ID-f429"
SID_FAIL_500="smoke-$RUN_ID-f500"
SID_DOWN="smoke-$RUN_ID-down"
MESSAGE="Smoke test $RUN_ID: in one short sentence, what colour is a clear daytime sky?"
HINT=""

VALID_META='(
  .metadata
  | (.model | type == "string" and length > 0)
    and (.latency_ms | type == "number" and . == floor and . >= 0)
    and (.input_tokens | type == "number" and . == floor)
    and (.output_tokens | type == "number" and . == floor)
    and (.fallback_attempts | type == "number" and . == floor))'
NON_EMPTY_REPLY='(.reply | type == "string" and (gsub("\\s"; "") | length) > 0)'

echo "${BOLD}Smoke testing ${BASE_URL}${RESET} ${DIM}(run ${RUN_ID})${RESET}"

# 1. health (retry while the host wakes up)
deadline=$(( $(date +%s) + WAIT_FOR_HEALTH ))
while :; do
  request GET /health
  [ "$STATUS" = "200" ] && break
  [ "$(date +%s)" -ge "$deadline" ] && break
  sleep 3
done
expect "health: 200 with status ok, keys_configured >= 2, cache_enabled boolean" 200 \
  '.status == "ok" and (.keys_configured | type == "number" and . >= 2) and (.cache_enabled | type == "boolean")'

# 2. live inference
chat "$SID_LIVE" "$MESSAGE"
LIVE_BODY="$BODY"
expect "chat: first message is LIVE_INFERENCE with full metadata and a key_id" 200 \
  ".session_id == \$sid and $NON_EMPTY_REPLY and .metadata.resolution_source == \"LIVE_INFERENCE\"
   and (.metadata.key_id | type == \"string\" and test(\"^key_[0-9]+$\")) and $VALID_META" \
  --arg sid "$SID_LIVE"

# 3. cache hit: same first message, new session
chat "$SID_CACHE" "$MESSAGE"
expect "cache: same message in a new session is LLM_CACHE, identical reply and tokens, key_id null, 0 fallbacks, faster" 200 \
  "$VALID_META and .metadata.resolution_source == \"LLM_CACHE\" and .metadata.key_id == null
   and .metadata.fallback_attempts == 0 and .reply == \$live.reply
   and .metadata.input_tokens == \$live.metadata.input_tokens
   and .metadata.output_tokens == \$live.metadata.output_tokens
   and .metadata.latency_ms < \$live.metadata.latency_ms" \
  --argjson live "${LIVE_BODY:-null}"

# 4. a different message never comes from the cache
chat "$SID_OTHER" "$MESSAGE Answer in French."
expect "cache: a different message is LIVE_INFERENCE" 200 '.metadata.resolution_source == "LIVE_INFERENCE"'

# 5. multi-turn memory
MEMORY_1="My favourite number is 42"
MEMORY_2="What is my favourite number?"
chat "$SID_MEMORY" "$MEMORY_1"
expect "memory: turn 1 answered" 200 "$NON_EMPTY_REPLY"
chat "$SID_MEMORY" "$MEMORY_2"
expect "memory: turn 2 remembers the number (reply mentions 42)" 200 '.reply | test("42")'

# 6. history endpoint
request GET "/sessions/$SID_MEMORY/messages"
expect "history: 4 messages, oldest first, no system prompt, metadata only on assistant messages" 200 \
  '.session_id == $sid and (.messages | length == 4)
   and ([.messages[].role] == ["user", "assistant", "user", "assistant"])
   and .messages[0].content == $m1 and .messages[2].content == $m2
   and ([.messages[] | select(.role == "user") | has("metadata")] | all(. == false))
   and ([.messages[] | select(.role == "assistant") | .metadata.resolution_source] | all(. == "LIVE_INFERENCE" or . == "LLM_CACHE"))' \
  --arg sid "$SID_MEMORY" --arg m1 "$MEMORY_1" --arg m2 "$MEMORY_2"

# 7. simulated failover
SIM_HINT="needs ENABLE_FAILURE_SIMULATION=true on the server"
for status in 429 500; do
  sid_var="SID_FAIL_$status"
  chat "${!sid_var}" "Failover check $status for $RUN_ID: say hello." "X-Simulate-Failure: key_1=$status"
  HINT="$SIM_HINT"
  expect "failover: X-Simulate-Failure key_1=$status -> 200 from key_2 with fallback_attempts 1" 200 \
    "$NON_EMPTY_REPLY and .metadata.key_id == \"key_2\" and .metadata.fallback_attempts == 1
     and .metadata.resolution_source == \"LIVE_INFERENCE\""
done

# 8. every key down -> 503, nothing stored
chat "$SID_DOWN" "Everything down check $RUN_ID" "X-Simulate-Failure: *=429"
HINT="$SIM_HINT"
expect "failover: X-Simulate-Failure *=429 -> 503 all providers unavailable" 503 \
  '. == {"detail": "all providers unavailable"}'
request GET "/sessions/$SID_DOWN/messages"
expect "failover: the failed session was not stored (history 404)" 404 '. == {"detail": "session not found"}'

# 9. validation errors
LONG_MESSAGE="$(printf '%4001s' '' | tr ' ' 'a')"
LONG_SESSION="$(printf '%129s' '' | tr ' ' 's')"
check_422() {
  request POST /chat "$2"
  expect "validation: $1 -> 422" 422 'has("detail")'
}
check_422 "missing message" '{"session_id": "smoke-v"}'
check_422 "empty message" '{"session_id": "smoke-v", "message": ""}'
check_422 "whitespace-only message" '{"session_id": "smoke-v", "message": "   \n\t "}'
check_422 "4001-char message" "$(jq -nc --arg m "$LONG_MESSAGE" '{session_id: "smoke-v", message: $m}')"
check_422 "missing session_id" '{"message": "hello"}'
check_422 "empty session_id" '{"session_id": "", "message": "hello"}'
check_422 "129-char session_id" "$(jq -nc --arg s "$LONG_SESSION" '{session_id: $s, message: "hello"}')"
check_422 "malformed JSON" '{"session_id": "smoke-v", "message": '

# 10. unknown session
request GET "/sessions/smoke-$RUN_ID-never-created/messages"
expect "history: unknown session -> 404 session not found" 404 '. == {"detail": "session not found"}'

echo
TOTAL=$((PASSED + FAILED))
if [ "$FAILED" -eq 0 ]; then
  echo "${GREEN}${BOLD}All ${TOTAL} checks passed${RESET}"
  exit 0
fi
echo "${RED}${BOLD}${FAILED} of ${TOTAL} checks failed${RESET}"
exit 1
