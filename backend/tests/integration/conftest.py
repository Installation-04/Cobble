"""Integration tests need real services. They are skipped unless configured.

COBBLE_TEST_DATABASE_URL   Postgres (required by all)
COBBLE_TEST_REDIS_URL      Redis (health, events)
COBBLE_TEST_LITELLM_URL / COBBLE_TEST_LITELLM_KEY   LiteLLM wired to the fake provider
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

BACKEND = Path(__file__).resolve().parents[2]


def require(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        pytest.skip(f"{name} is not set")
    return value


def alembic_config(url: str) -> Config:
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "migrations"))
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return config


@pytest.fixture
def database_url() -> str:
    return require("COBBLE_TEST_DATABASE_URL")


@pytest.fixture
def redis_url() -> str:
    return require("COBBLE_TEST_REDIS_URL")


@pytest.fixture
def migrated_database(database_url: str) -> str:
    command.upgrade(alembic_config(database_url), "head")
    return database_url
