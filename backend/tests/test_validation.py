import pytest

from tests.conftest import chat


@pytest.mark.parametrize(
    "payload",
    [
        {"session_id": "s-1"},  # missing message
        {"session_id": "s-1", "message": ""},
        {"session_id": "s-1", "message": "   \n\t  "},
        {"session_id": "s-1", "message": "x" * 4001},
        {"session_id": "s-1", "message": None},
        {"session_id": "s-1", "message": 123},
        {"message": "hello"},  # missing session_id
        {"session_id": "", "message": "hello"},
        {"session_id": "   ", "message": "hello"},
        {"session_id": "s" * 129, "message": "hello"},
        {"session_id": "s-1", "message": "hello", "system_prompt": "p" * 8001},
    ],
)
def test_invalid_payloads_return_422(client, payload):
    res = client.post("/chat", json=payload)
    assert res.status_code == 422
    assert "detail" in res.json()


def test_malformed_json_returns_422(client):
    res = client.post("/chat", content=b'{"session_id": "s-1", "message": ', headers={"Content-Type": "application/json"})
    assert res.status_code == 422
    assert "detail" in res.json()


def test_rejected_request_creates_no_session(client, new_session):
    sid = new_session()
    assert chat(client, sid, "   ").status_code == 422
    assert client.get(f"/sessions/{sid}/messages").status_code == 404


def test_4000_chars_with_surrounding_whitespace_is_accepted_and_trimmed(client, new_session, fake_llm):
    sid = new_session()
    message = "y" * 4000
    res = chat(client, sid, f"   {message}  \n")
    assert res.status_code == 200
    stored = client.get(f"/sessions/{sid}/messages").json()["messages"][0]
    assert stored["content"] == message
    sent = fake_llm.requests[-1]["body"]["messages"][-1]
    assert sent == {"role": "user", "content": message}


def test_128_char_session_id_is_accepted(client):
    assert chat(client, "s" * 128, "hello").status_code == 200
