"""Application settings, read from environment variables (and an optional .env file)."""

from __future__ import annotations

from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # ../.env lets `uvicorn` run from /backend with the repo-root .env during local dev.
    model_config = SettingsConfigDict(env_file=("../.env", ".env"), extra="ignore")

    llm_api_keys: str = ""
    llm_model: str = "gemini/gemini-3.5-flash"
    llm_api_base: str | None = None
    llm_timeout_seconds: float = 20.0
    llm_temperature: float = 0.2
    llm_max_tokens: int = 1024

    database_url: str = "sqlite:///./app.db"
    allowed_origins: str = "http://localhost:3000,http://localhost:5173"
    enable_failure_simulation: bool = False
    default_system_prompt: str = "You are a helpful, concise assistant."
    history_max_messages: int = 40

    cache_type: Literal["local", "disk"] = "local"
    cache_dir: str = "/data/litellm_cache"
    log_level: str = "INFO"

    @field_validator("llm_api_base", mode="before")
    @classmethod
    def _blank_is_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("cache_type", "log_level", mode="before")
    @classmethod
    def _normalise_case(cls, value: object) -> object:
        return value.strip().lower() if isinstance(value, str) else value

    @property
    def api_keys(self) -> list[str]:
        """The ordered key pool. Index 0 is key_1, index 1 is key_2, and so on."""
        return [k.strip() for k in self.llm_api_keys.split(",") if k.strip()]

    @property
    def origins(self) -> list[str]:
        return [o.strip().rstrip("/") for o in self.allowed_origins.split(",") if o.strip()]

    @property
    def database_path(self) -> str:
        """sqlite:////data/app.db -> /data/app.db, sqlite:///./app.db -> ./app.db"""
        prefix = "sqlite:///"
        if not self.database_url.startswith(prefix):
            raise ValueError("DATABASE_URL must look like sqlite:///relative.db or sqlite:////abs/path.db")
        path = self.database_url[len(prefix):].split("?", 1)[0]
        if not path:
            raise ValueError("DATABASE_URL has no file path")
        return path
