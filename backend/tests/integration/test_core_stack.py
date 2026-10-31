from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from redis import Redis
from sqlalchemy import select

from cobble.api.app import create_app, default_checks
from cobble.config import Settings
from cobble.db import LLMCall, make_engine, make_session_factory
from cobble.events import EVENTS_STREAM
from cobble.router.gateway import LiteLLMGateway

from .conftest import require

pytestmark = pytest.mark.integration


def test_health_against_real_services(migrated_database: str, redis_url: str) -> None:
    settings = Settings(database_url=migrated_database, redis_url=redis_url)
    client = TestClient(create_app(default_checks(settings)))
    reply = client.get("/api/v1/health")
    assert reply.status_code == 200
    assert reply.json()["status"] == "ok"


def test_health_is_503_when_database_is_unreachable(redis_url: str) -> None:
    settings = Settings(
        database_url="postgresql+psycopg://x:x@127.0.0.1:1/none?connect_timeout=1",
        redis_url=redis_url,
    )
    client = TestClient(create_app(default_checks(settings)))
    reply = client.get("/api/v1/health")
    assert reply.status_code == 503
    assert reply.json()["database"] == "error"


def test_chat_through_litellm_returns_cassette_and_records_cost(
    migrated_database: str, redis_url: str
) -> None:
    litellm_url = require("COBBLE_TEST_LITELLM_URL")
    litellm_key = require("COBBLE_TEST_LITELLM_KEY")
    sessions = make_session_factory(make_engine(migrated_database))
    redis = Redis.from_url(redis_url)
    before = int(redis.xlen(EVENTS_STREAM))

    gateway = LiteLLMGateway(litellm_url, litellm_key, sessions, redis)
    result = gateway.chat("fake", [{"role": "user", "content": "hello"}])

    # The reply is the "hello" cassette recorded in providers/fake-llm/cassettes.
    assert "Cobble fake LLM" in result.content
    assert result.prompt_tokens > 0
    assert result.completion_tokens > 0
    assert result.cost_usd > Decimal(0)

    with sessions() as session:
        row = session.scalars(select(LLMCall).order_by(LLMCall.created_at.desc())).first()
    assert row is not None
    assert row.model == "fake"
    assert row.prompt_tokens == result.prompt_tokens
    assert row.completion_tokens == result.completion_tokens
    assert row.cost_usd > Decimal(0)
    assert int(redis.xlen(EVENTS_STREAM)) == before + 1
