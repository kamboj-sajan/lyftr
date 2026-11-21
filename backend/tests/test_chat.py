from tests.conftest import chat

METADATA_TYPES = {
    "resolution_source": str,
    "model": str,
    "latency_ms": int,
    "input_tokens": int,
    "output_tokens": int,
    "fallback_attempts": int,
}


def test_happy_path_returns_full_metadata(client, new_session):
    sid = new_session()
    res = chat(client, sid, "What is the capital of France?")
    assert res.status_code == 200
    body = res.json()
    assert body["session_id"] == sid
    assert body["reply"] == "Fake reply to: What is the capital of France?"
    meta = body["metadata"]
    for field, typ in METADATA_TYPES.items():
        assert isinstance(meta[field], typ), field
        assert not isinstance(meta[field], bool), field
    assert meta["resolution_source"] == "LIVE_INFERENCE"
    assert meta["model"] == "openai/fake-model"  # the configured LiteLLM string, provider prefix kept
    assert meta["key_id"] == "key_1"
    assert meta["fallback_attempts"] == 0
    assert meta["latency_ms"] >= 300  # the fake provider sleeps 300 ms
    assert meta["input_tokens"] > 0 and meta["output_tokens"] > 0


def test_same_first_message_in_new_session_is_served_from_cache(client, new_session, fake_llm):
    first = chat(client, new_session(), "Cache this question please").json()
    calls_after_first = len(fake_llm.requests)
    # Sent immediately: the cache write must already be done.
    second = chat(client, new_session(), "Cache this question please").json()

    assert first["metadata"]["resolution_source"] == "LIVE_INFERENCE"
    assert second["metadata"]["resolution_source"] == "LLM_CACHE"
    assert second["reply"] == first["reply"]
    assert second["metadata"]["input_tokens"] == first["metadata"]["input_tokens"]
    assert second["metadata"]["output_tokens"] == first["metadata"]["output_tokens"]
    assert second["metadata"]["key_id"] is None
    assert second["metadata"]["fallback_attempts"] == 0
    assert second["metadata"]["model"] == first["metadata"]["model"]
    assert second["metadata"]["latency_ms"] < first["metadata"]["latency_ms"]
    assert second["metadata"]["latency_ms"] < 100
    assert len(fake_llm.requests) == calls_after_first  # the provider was not called


def test_different_message_is_never_served_from_cache(client, new_session):
    chat(client, new_session(), "First distinct message")
    res = chat(client, new_session(), "Second distinct message").json()
    assert res["metadata"]["resolution_source"] == "LIVE_INFERENCE"
    assert res["reply"] == "Fake reply to: Second distinct message"


def test_follow_up_turn_has_different_context_so_it_is_not_cached(client, new_session):
    sid_a, sid_b = new_session(), new_session()
    chat(client, sid_a, "Hello there")
    chat(client, sid_a, "And again")
    # Same text, but session B has no history: a different message list, so live.
    res = chat(client, sid_b, "And again").json()
    assert res["metadata"]["resolution_source"] == "LIVE_INFERENCE"


def test_multi_turn_sends_history_to_provider(client, new_session, fake_llm):
    sid = new_session()
    chat(client, sid, "My favourite number is 42")
    fake_llm.reset()
    reply = chat(client, sid, "What is my favourite number?").json()["reply"]
    assert "42" in reply  # the fake provider only "remembers" what the history contains
    sent = fake_llm.requests[-1]["body"]["messages"]
    assert [m["role"] for m in sent] == ["system", "user", "assistant", "user"]
    assert sent[0]["content"] == "You are a test assistant."
    assert sent[1]["content"] == "My favourite number is 42"
    assert sent[2]["content"] == "Fake reply to: My favourite number is 42"
    assert sent[3]["content"] == "What is my favourite number?"


def test_sessions_are_isolated(client, new_session, fake_llm):
    sid_a, sid_b = new_session(), new_session()
    chat(client, sid_a, "Secret for session A")
    fake_llm.reset()
    chat(client, sid_b, "Hello from B")
    sent = fake_llm.requests[-1]["body"]["messages"]
    assert all("Secret for session A" not in m["content"] for m in sent)
    assert len(client.get(f"/sessions/{sid_b}/messages").json()["messages"]) == 2


def test_tokens_are_per_request_not_cumulative(client, new_session):
    a = chat(client, new_session(), "alpha message 1").json()["metadata"]
    b = chat(client, new_session(), "bravo message 2").json()["metadata"]
    assert a["input_tokens"] == b["input_tokens"]  # equal-length first messages

    sid = new_session()
    turn1 = chat(client, sid, "one two three").json()
    turn2 = chat(client, sid, "four five six").json()
    # The fake provider reports completion_tokens = words in its reply.
    assert turn2["metadata"]["output_tokens"] == len(turn2["reply"].split())
    assert turn2["metadata"]["output_tokens"] != (
        turn1["metadata"]["output_tokens"] + len(turn2["reply"].split())
    )


def test_history_window_is_limited(make_client, new_session, fake_llm):
    client = make_client(history_max_messages=2)
    sid = new_session()
    for text in ("turn one", "turn two", "turn three"):
        chat(client, sid, text)
    sent = fake_llm.requests[-1]["body"]["messages"]
    assert [m["content"] for m in sent[1:]] == ["turn two", "Fake reply to: turn two", "turn three"]


def test_system_prompt_is_persisted_per_session(client, new_session, fake_llm):
    sid = new_session()
    chat(client, sid, "Ahoy", system_prompt="You are a pirate.")
    assert fake_llm.requests[-1]["body"]["messages"][0] == {"role": "system", "content": "You are a pirate."}

    chat(client, sid, "Still a pirate?")  # no override: stored prompt is used
    assert fake_llm.requests[-1]["body"]["messages"][0]["content"] == "You are a pirate."

    chat(client, sid, "Blank means not provided", system_prompt="   ")
    assert fake_llm.requests[-1]["body"]["messages"][0]["content"] == "You are a pirate."

    chat(client, new_session(), "Other session uses the default")
    assert fake_llm.requests[-1]["body"]["messages"][0]["content"] == "You are a test assistant."

    history = client.get(f"/sessions/{sid}/messages").json()["messages"]
    assert all(m["role"] != "system" for m in history)
