from __future__ import annotations

import uuid
from collections.abc import Iterator
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from cobble.db import Base, LLMCall, make_session_factory
from cobble.router.gateway import GatewayError, LiteLLMGateway

from .fakes import FakeRedis


@pytest.fixture
def sessions() -> Iterator[sessionmaker[Session]]:
    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    yield make_session_factory(engine)
    engine.dispose()


def litellm(status: int = 200, cost: str | None = "0.00042") -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat/completions"
        headers = {"x-litellm-call-id": "call-1"}
        if cost is not None:
            headers["x-litellm-response-cost"] = cost
        return httpx.Response(
            status,
            headers=headers,
            json={
                "id": "chatcmpl-1",
                "model": "fake",
                "choices": [{"message": {"content": "hi there"}}],
                "usage": {"prompt_tokens": 3, "completion_tokens": 2},
            },
        )

    return httpx.Client(transport=httpx.MockTransport(handler), base_url="http://litellm")


def test_chat_records_tokens_and_cost(sessions: sessionmaker[Session]) -> None:
    redis = FakeRedis()
    gateway = LiteLLMGateway("http://litellm", "k", sessions, redis, litellm())  # type: ignore[arg-type]
    project, task = uuid.uuid4(), uuid.uuid4()
    result = gateway.chat(
        "fake",
        [{"role": "user", "content": "hello"}],
        role="worker",
        project_id=project,
        task_id=task,
    )
    assert result.content == "hi there"
    assert result.cost_usd == Decimal("0.00042")

    with sessions() as session:
        row = session.scalars(select(LLMCall)).one()
    assert (row.model, row.role) == ("fake", "worker")
    assert (row.prompt_tokens, row.completion_tokens) == (3, 2)
    assert row.cost_usd == Decimal("0.00042000")
    assert (row.project_id, row.task_id, row.request_id) == (project, task, "call-1")

    assert redis.added[0][1]["type"] == "llm.call.completed"


def test_missing_cost_header_records_zero(sessions: sessionmaker[Session]) -> None:
    gateway = LiteLLMGateway("http://litellm", "", sessions, None, litellm(cost=None))
    assert gateway.chat("fake", []).cost_usd == Decimal(0)


def test_gateway_error_records_nothing(sessions: sessionmaker[Session]) -> None:
    gateway = LiteLLMGateway("http://litellm", "", sessions, None, litellm(status=500))
    with pytest.raises(GatewayError) as info:
        gateway.chat("fake", [])
    assert info.value.status == 500
    with sessions() as session:
        assert session.scalars(select(LLMCall)).all() == []
