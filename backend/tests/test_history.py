from tests.conftest import chat


def test_history_is_oldest_first_without_system_prompt(client, new_session):
    sid = new_session()
    chat(client, sid, "My favourite number is 42", system_prompt="Remember numbers.")
    chat(client, sid, "What is my favourite number?")

    res = client.get(f"/sessions/{sid}/messages")
    assert res.status_code == 200
    body = res.json()
    assert body["session_id"] == sid
    messages = body["messages"]
    assert [m["role"] for m in messages] == ["user", "assistant", "user", "assistant"]
    assert messages[0]["content"] == "My favourite number is 42"
    assert messages[2]["content"] == "What is my favourite number?"
    assert all("Remember numbers." not in m["content"] for m in messages)

    for m in messages:
        if m["role"] == "user":
            assert "metadata" not in m
        else:
            meta = m["metadata"]
            assert meta["resolution_source"] == "LIVE_INFERENCE"
            assert isinstance(meta["input_tokens"], int) and isinstance(meta["output_tokens"], int)
            assert meta["key_id"] == "key_1"


def test_history_keeps_cache_metadata(client, new_session):
    chat(client, new_session(), "same question")
    sid = new_session()
    chat(client, sid, "same question")
    assistant = client.get(f"/sessions/{sid}/messages").json()["messages"][1]
    assert assistant["metadata"]["resolution_source"] == "LLM_CACHE"
    assert assistant["metadata"]["key_id"] is None


def test_unknown_session_returns_404(client):
    res = client.get("/sessions/s-does-not-exist/messages")
    assert res.status_code == 404
    assert res.json() == {"detail": "session not found"}


def test_trailing_slash_route_is_not_served(client, new_session):
    sid = new_session()
    chat(client, sid, "hi")
    assert client.get(f"/sessions/{sid}/messages/", follow_redirects=False).status_code == 404
    assert client.post("/chat/", json={"session_id": sid, "message": "hi"}, follow_redirects=False).status_code == 404
    assert client.get("/health/", follow_redirects=False).status_code == 404


def test_history_survives_a_new_app_instance(make_client, new_session):
    sid = new_session()
    first_app = make_client()
    chat(first_app, sid, "persist me")

    second_app = make_client()  # same DB file, fresh process state and cache
    messages = second_app.get(f"/sessions/{sid}/messages").json()["messages"]
    assert [m["content"] for m in messages] == ["persist me", "Fake reply to: persist me"]

    # and the conversation continues with the stored history
    chat(second_app, sid, "still there?")
    assert len(second_app.get(f"/sessions/{sid}/messages").json()["messages"]) == 4
