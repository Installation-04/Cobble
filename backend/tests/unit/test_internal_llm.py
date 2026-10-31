from __future__ import annotations

import uuid
from collections.abc import Iterator
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from cobble.api.app import create_app
from cobble.auth import runtoken
from cobble.capabilities import ChatResult, Role
from cobble.config import Settings
from cobble.db import Base, make_session_factory
from cobble.router.budget import BudgetExceeded
from cobble.router.gateway import GatewayError

from .fakes import CounterRedis

SECRET = "internal-llm-secret"
URL = "/internal/llm/v1/chat/completions"
TASK, PROJECT = uuid.uuid4(), uuid.uuid4()


class FakeRouter:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.error: Exception | None = None

    def chat(self, role: Role, messages: list[dict[str, Any]], **kw: Any) -> ChatResult:
        self.calls.append({"role": role, "messages": messages, **kw})
        if self.error:
            raise self.error
        return ChatResult("edited file", "fake", 12, 3, Decimal("0.001"), None)


@pytest.fixture
def sessions() -> Iterator[sessionmaker[Session]]:
    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    yield make_session_factory(engine)
    engine.dispose()


@pytest.fixture
def router() -> FakeRouter:
    return FakeRouter()


@pytest.fixture
def client(sessions: sessionmaker[Session], router: FakeRouter) -> TestClient:
    app = create_app(
        settings=Settings(run_token_secret=SECRET),
        session_factory=sessions,
        redis=CounterRedis(),
    )
    app.state.cost_router = router
    return TestClient(app)


def token(**kw: Any) -> str:
    args: dict[str, Any] = {
        "task_id": TASK,
        "project_id": PROJECT,
        "role": "worker",
        "ttl_s": 600,
    }
    args.update(kw)
    return runtoken.issue(SECRET, **args)


BODY = {"model": "gpt-attacker", "messages": [{"role": "user", "content": "do it", "x": 1}]}


def post(client: TestClient, tok: str | None, body: dict[str, Any] | None = None) -> Any:
    headers = {"Authorization": f"Bearer {tok}"} if tok else {}
    return client.post(URL, json=BODY if body is None else body, headers=headers)


def test_valid_call_goes_through_the_router_with_the_tokens_identity(
    client: TestClient, router: FakeRouter
) -> None:
    reply = post(client, token())  # note: no CSRF header, bearer auth only
    assert reply.status_code == 200
    data = reply.json()
    assert data["choices"][0]["message"]["content"] == "edited file"
    assert data["usage"] == {"prompt_tokens": 12, "completion_tokens": 3, "total_tokens": 15}
    call = router.calls[0]
    assert call["role"] is Role.WORKER
    assert (call["project_id"], call["task_id"]) == (PROJECT, TASK)
    assert call["model"] is None, "the model named in the request body must be ignored"
    assert call["messages"] == [{"role": "user", "content": "do it"}], "unknown keys dropped"


def test_escalation_model_comes_from_the_token(client: TestClient, router: FakeRouter) -> None:
    post(client, token(model_override="strong"))
    assert router.calls[0]["model"] == "strong"


@pytest.mark.parametrize("bad", [None, "garbage", "a.b"])
def test_missing_or_invalid_token_is_401(client: TestClient, router: FakeRouter, bad: Any) -> None:
    reply = post(client, bad)
    assert reply.status_code == 401
    assert reply.json()["error"]["code"] == "invalid_token"
    assert router.calls == []


def test_expired_token_and_unknown_role_are_401(client: TestClient) -> None:
    assert post(client, token(ttl_s=-10)).status_code == 401
    assert post(client, token(role="admin")).status_code == 401


def test_budget_reached_is_402(client: TestClient, router: FakeRouter) -> None:
    router.error = BudgetExceeded(PROJECT)
    reply = post(client, token())
    assert reply.status_code == 402
    assert reply.json()["error"]["code"] == "budget_reached"


def test_gateway_error_is_502(client: TestClient, router: FakeRouter) -> None:
    router.error = GatewayError(500)
    reply = post(client, token())
    assert reply.status_code == 502
    assert reply.json()["error"]["code"] == "llm_error"


def test_streaming_and_empty_messages_are_rejected(client: TestClient) -> None:
    streaming = {"messages": [{"role": "user", "content": "x"}], "stream": True}
    assert post(client, token(), streaming).status_code == 400
    assert post(client, token(), {"messages": []}).status_code == 422


def test_public_api_still_requires_the_csrf_header(client: TestClient) -> None:
    reply = client.post("/api/v1/auth/login", json={"email": "a@b.co", "password": "x"})
    assert reply.status_code == 403
