from __future__ import annotations

import uuid
from typing import Callable, Iterator

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from tests.fake_llm import FakeLLMServer

KEY_1 = "test-key-alpha-1111"
KEY_2 = "test-key-bravo-2222"


@pytest.fixture(scope="session")
def fake_llm() -> Iterator[FakeLLMServer]:
    server = FakeLLMServer(delay_seconds=0.3).start()
    yield server
    server.stop()


@pytest.fixture
def make_settings(tmp_path, fake_llm) -> Callable[..., Settings]:
    def _make(**overrides) -> Settings:
        values = dict(
            llm_api_keys=f"{KEY_1},{KEY_2}",
            llm_model="openai/fake-model",
            llm_api_base=fake_llm.base_url,
            llm_timeout_seconds=5,
            llm_temperature=0.2,
            llm_max_tokens=256,
            database_url=f"sqlite:///{tmp_path}/test.db",
            allowed_origins="http://localhost:3000, http://localhost:5173/",
            enable_failure_simulation=True,
            default_system_prompt="You are a test assistant.",
            history_max_messages=40,
            cache_type="local",
            cache_dir=str(tmp_path / "cache"),
            log_level="INFO",
        )
        values.update(overrides)
        return Settings(_env_file=None, **values)

    return _make


@pytest.fixture
def make_client(make_settings, fake_llm) -> Iterator[Callable[..., TestClient]]:
    """Build a fresh app (own DB file, own cache) and run its lifespan."""
    opened: list[TestClient] = []

    def _make(**overrides) -> TestClient:
        client = TestClient(create_app(make_settings(**overrides)), raise_server_exceptions=False)
        client.__enter__()
        opened.append(client)
        return client

    fake_llm.reset()
    yield _make
    for client in opened:
        client.__exit__(None, None, None)


@pytest.fixture
def client(make_client) -> TestClient:
    return make_client()


@pytest.fixture
def new_session() -> Callable[[], str]:
    return lambda: f"s-{uuid.uuid4()}"


def chat(client: TestClient, session_id: str, message: str, headers: dict | None = None, **extra):
    return client.post("/chat", json={"session_id": session_id, "message": message, **extra}, headers=headers or {})
