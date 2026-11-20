import pytest
from fastapi.testclient import TestClient

from app.main import create_app


def test_health_shape_and_types(client):
    res = client.get("/health")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert body["keys_configured"] == 2 and isinstance(body["keys_configured"], int)
    assert body["cache_enabled"] is True


def test_health_503_when_database_unreachable(client, monkeypatch):
    async def broken_ping():
        return False

    monkeypatch.setattr(client.app.state.db, "ping", broken_ping)
    res = client.get("/health")
    assert res.status_code == 503
    assert "detail" in res.json()


@pytest.mark.parametrize("keys", ["", "only-one-key", " , only-one-key , "])
def test_startup_fails_fast_with_fewer_than_two_keys(make_settings, keys, caplog):
    app = create_app(make_settings(llm_api_keys=keys))
    with pytest.raises(ValueError, match="at least 2"):
        with TestClient(app):
            pass
    assert "only-one-key" not in caplog.text


def test_three_keys_are_numbered_in_order(make_client):
    client = make_client(llm_api_keys="a-key,b-key,c-key")
    assert client.get("/health").json()["keys_configured"] == 3
    assert client.app.state.gateway.key_ids == ["key_1", "key_2", "key_3"]
