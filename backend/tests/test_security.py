import logging

from tests.conftest import KEY_1, KEY_2, chat


def test_no_key_value_appears_in_any_response_or_log(client, new_session, caplog):
    caplog.set_level(logging.DEBUG)
    sid = new_session()
    bodies = [
        client.get("/health").text,
        chat(client, sid, "hello keys").text,
        chat(client, new_session(), "hello keys").text,  # cache hit
        chat(client, sid, "failover", headers={"X-Simulate-Failure": "key_1=429"}).text,
        chat(client, new_session(), "down", headers={"X-Simulate-Failure": "*=503"}).text,
        client.get(f"/sessions/{sid}/messages").text,
        client.post("/chat", json={"session_id": sid}).text,
    ]
    for text in bodies + [caplog.text]:
        assert KEY_1 not in text
        assert KEY_2 not in text


def test_real_provider_error_text_is_not_leaked(make_client, new_session):
    client = make_client(llm_api_keys="rate-key-x,boom-key-y")
    res = chat(client, new_session(), "leak check")
    assert res.status_code == 503
    assert res.json() == {"detail": "all providers unavailable"}
    assert "fake 429" not in res.text and "rate-key-x" not in res.text


def test_internal_error_returns_json_500_without_traceback(client, new_session):
    async def explode(*args, **kwargs):
        raise RuntimeError("secret internal detail")

    client.app.state.db.get_session = explode
    res = chat(client, new_session(), "trigger a bug")
    assert res.status_code == 500
    assert res.json() == {"detail": "internal server error"}
    assert "Traceback" not in res.text and "secret internal detail" not in res.text


def test_internal_error_still_has_cors_headers(client, new_session):
    async def explode(*args, **kwargs):
        raise RuntimeError("boom")

    client.app.state.db.get_session = explode
    res = client.post(
        "/chat",
        json={"session_id": new_session(), "message": "cors on 500"},
        headers={"Origin": "http://localhost:3000"},
    )
    assert res.status_code == 500
    assert res.headers.get("access-control-allow-origin") == "http://localhost:3000"


def test_cors_preflight_allows_configured_origin_and_simulation_header(client):
    res = client.options(
        "/chat",
        headers={
            "Origin": "http://localhost:5173",  # configured with a trailing slash, which is stripped
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type,x-simulate-failure",
        },
    )
    assert res.status_code == 200
    assert res.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert "x-simulate-failure" in res.headers["access-control-allow-headers"].lower()


def test_cors_rejects_unknown_origin(client):
    res = client.get("/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in res.headers
