"""Runtime configuration, read from COBBLE_* environment variables."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="COBBLE_", extra="ignore")

    database_url: str = "postgresql+psycopg://cobble:cobble@localhost:5432/cobble"
    redis_url: str = "redis://localhost:6379/0"
    litellm_url: str = "http://localhost:4000"
    litellm_key: str = ""
    default_model: str = "fake"
    lang: str = "en"
    public_url: str = "http://localhost:8080"
    cookie_secure: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()
