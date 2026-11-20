import pytest

from app.llm.simulation import parse_simulation_header
from tests.conftest import KEY_1, KEY_2, chat

KEYS = ["key_1", "key_2"]
UNAVAILABLE = {"detail": "all providers unavailable"}


# -- header parsing -----------------------------------------------------------


@pytest.mark.parametrize(
    "header, expected",
    [
        (None, {}),
        ("", {}),
        ("key_1=429", {"key_1": 429}),
        (" key_1 = 500 , key_2=502 ", {"key_1": 500, "key_2": 502}),
        ("*=503", {"key_1": 503, "key_2": 503}),
        ("*=429,key_2=500", {"key_1": 429, "key_2": 500}),  # specific overrides *
        ("key_2=500,*=429", {"key_1": 429, "key_2": 500}),
        ("key_9=429", {}),  # unknown key id
        ("key_1=418", {}),  # unsupported status
        ("key_1", {}),
        ("=429", {}),
        ("key_1=abc,,key_2=429", {"key_2": 429}),
    ],
)
def test_parse_simulation_header(header, expected):
    assert parse_simulation_header(header, KEYS) == expected


# -- simulated failures (X-Simulate-Failure) ---------------------------------------


@pytest.mark.parametrize("status", [429, 500, 502, 503])
def test_simulated_key_1_failure_falls_over_to_key_2(client, new_session, fake_llm, status):
    res = chat(client, new_session(), f"simulate {status}", headers={"X-Simulate-Failure": f"key_1={status}"})
    assert res.status_code == 200
    body = res.json()
    meta = body["metadata"]
    assert meta["key_id"] == "key_2"
    assert meta["fallback_attempts"] == 1
    assert meta["resolution_source"] == "LIVE_INFERENCE"
    assert body["reply"] == f"Fake reply to: simulate {status}"  # a real answer, not an error text
    assert meta["attempts"][0] == {"key_id": "key_1", "status": status, "outcome": "error", "simulated": True,
                                   "ms": meta["attempts"][0]["ms"]}
    assert meta["attempts"][1]["key_id"] == "key_2" and meta["attempts"][1]["outcome"] == "success"
    # The simulated key never reached the provider; key_2 did, exactly once.
    assert fake_llm.calls_for(KEY_1) == []
    assert len(fake_llm.calls_for(KEY_2)) == 1


def test_all_keys_simulated_down_returns_503_and_writes_nothing(client, new_session, fake_llm):
    sid = new_session()
    res = chat(client, sid, "nobody home", headers={"X-Simulate-Failure": "*=429"})
    assert res.status_code == 503
    assert res.json() == UNAVAILABLE
    assert fake_llm.requests == []
    assert client.get(f"/sessions/{sid}/messages").status_code == 404


def test_failed_request_does_not_touch_existing_history(client, new_session):
    sid = new_session()
    chat(client, sid, "first turn")
    assert chat(client, sid, "second turn", headers={"X-Simulate-Failure": "*=500"}).status_code == 503
    messages = client.get(f"/sessions/{sid}/messages").json()["messages"]
    assert [m["content"] for m in messages] == ["first turn", "Fake reply to: first turn"]


def test_simulation_is_per_request_only(client, new_session):
    chat(client, new_session(), "warm the cache", headers={"X-Simulate-Failure": "key_1=429"})
    # The next request has no header: key_1 is healthy again (no cooldown leaked).
    res = chat(client, new_session(), "a brand new message").json()
    assert res["metadata"]["key_id"] == "key_1"
    assert res["metadata"]["fallback_attempts"] == 0


def test_simulated_request_skips_cache_read_but_still_writes(client, new_session):
    chat(client, new_session(), "cached question")  # now in the cache
    simulated = chat(client, new_session(), "cached question", headers={"X-Simulate-Failure": "key_1=500"}).json()
    assert simulated["metadata"]["resolution_source"] == "LIVE_INFERENCE"
    assert simulated["metadata"]["key_id"] == "key_2"

    chat(client, new_session(), "only via simulation", headers={"X-Simulate-Failure": "key_1=429"})
    plain = chat(client, new_session(), "only via simulation").json()
    assert plain["metadata"]["resolution_source"] == "LLM_CACHE"


def test_ignored_header_does_not_skip_the_cache(client, new_session):
    chat(client, new_session(), "cache me once")
    res = chat(client, new_session(), "cache me once", headers={"X-Simulate-Failure": "key_7=429"}).json()
    assert res["metadata"]["resolution_source"] == "LLM_CACHE"


def test_header_is_ignored_when_simulation_disabled(make_client, new_session, fake_llm):
    client = make_client(enable_failure_simulation=False)
    res = chat(client, new_session(), "simulation off", headers={"X-Simulate-Failure": "*=429"})
    assert res.status_code == 200
    assert res.json()["metadata"]["key_id"] == "key_1"
    assert res.json()["metadata"]["fallback_attempts"] == 0
    assert len(fake_llm.calls_for(KEY_1)) == 1


# -- real provider failures (from the fake server, no simulation) -------------------


@pytest.mark.parametrize("bad_key", ["rate-limited-key", "boom-key", "unavail-key", "dead-key"])
def test_real_provider_failure_falls_over(make_client, new_session, fake_llm, bad_key):
    client = make_client(llm_api_keys=f"{bad_key},{KEY_2}", enable_failure_simulation=False)
    res = chat(client, new_session(), "real failover")
    assert res.status_code == 200
    meta = res.json()["metadata"]
    assert meta["key_id"] == "key_2"
    assert meta["fallback_attempts"] == 1
    assert meta["attempts"][0]["simulated"] is False
    assert len(fake_llm.calls_for(bad_key)) == 1  # no provider-level retries


def test_three_keys_two_failures(make_client, new_session):
    client = make_client(llm_api_keys=f"rate-key,boom-key,{KEY_2}")
    meta = chat(client, new_session(), "third time lucky").json()["metadata"]
    assert meta["key_id"] == "key_3"
    assert meta["fallback_attempts"] == 2


def test_all_real_keys_failing_returns_503(make_client, new_session):
    client = make_client(llm_api_keys="rate-key,boom-key")
    sid = new_session()
    res = chat(client, sid, "everything is down")
    assert res.status_code == 503
    assert res.json() == UNAVAILABLE
    assert client.get(f"/sessions/{sid}/messages").status_code == 404


def test_request_caused_400_does_not_burn_other_keys(make_client, new_session, fake_llm):
    client = make_client(llm_api_keys=f"badreq-key,{KEY_2}")
    res = chat(client, new_session(), "a bad request")
    assert res.status_code == 503
    assert res.json() == UNAVAILABLE
    assert fake_llm.calls_for(KEY_2) == []


def test_empty_reply_counts_as_failed_attempt_and_is_not_cached(make_client, new_session):
    client = make_client(llm_api_keys=f"empty-key,{KEY_2}")
    first = chat(client, new_session(), "please answer").json()
    assert first["reply"] == "Fake reply to: please answer"
    assert first["metadata"]["key_id"] == "key_2"
    assert first["metadata"]["fallback_attempts"] == 1
    assert first["metadata"]["attempts"][0]["outcome"] == "empty"


def test_only_empty_replies_returns_503(make_client, new_session):
    client = make_client(llm_api_keys="empty-key-1,empty-key-2")
    res = chat(client, new_session(), "silence")
    assert res.status_code == 503
    assert res.json() == UNAVAILABLE
