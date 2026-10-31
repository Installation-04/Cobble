from __future__ import annotations

import uuid
from collections.abc import Iterator
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from cobble.capabilities import ChatResult, Role
from cobble.db import Base, LLMCall, Project, User, make_session_factory
from cobble.router.budget import BudgetExceeded, BudgetService, apply_budget
from cobble.router.costs import CostRouter

from .fakes import FakeRedis


@pytest.fixture
def sessions() -> Iterator[sessionmaker[Session]]:
    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    yield make_session_factory(engine)
    engine.dispose()


class RecordingGateway:
    """Stands in for LiteLLMGateway: records an LLMCall row with a fixed cost."""

    def __init__(self, sessions: sessionmaker[Session], cost: str) -> None:
        self.sessions = sessions
        self.cost = Decimal(cost)
        self.calls: list[tuple[str, str | None]] = []

    def chat(
        self,
        model: str,
        messages: list[dict[str, Any]],
        *,
        role: str | None = None,
        project_id: uuid.UUID | None = None,
        task_id: uuid.UUID | None = None,
    ) -> ChatResult:
        self.calls.append((model, role))
        with self.sessions() as session:
            session.add(
                LLMCall(
                    model=model,
                    role=role,
                    project_id=project_id,
                    task_id=task_id,
                    prompt_tokens=1,
                    completion_tokens=1,
                    cost_usd=self.cost,
                )
            )
            session.commit()
        return ChatResult("ok", model, 1, 1, self.cost, None)


def make_project(sessions: sessionmaker[Session], budget: str | None) -> uuid.UUID:
    with sessions() as session:
        user = User(email="a@b.co", password_hash="x")
        session.add(user)
        session.flush()
        project = Project(
            owner_id=user.id, name="p", budget_usd=Decimal(budget) if budget else None
        )
        session.add(project)
        session.commit()
        return project.id


def status(sessions: sessionmaker[Session], project_id: uuid.UUID) -> str:
    with sessions() as session:
        project = session.get(Project, project_id)
        assert project is not None
        return project.status


def event_types(redis: FakeRedis) -> list[str]:
    return [fields["type"] for _stream, fields in redis.added]


def build(
    sessions: sessionmaker[Session], cost: str
) -> tuple[CostRouter, RecordingGateway, FakeRedis]:
    redis = FakeRedis()
    gateway = RecordingGateway(sessions, cost)
    budget = BudgetService(sessions, redis)  # type: ignore[arg-type]
    router = CostRouter(
        gateway, budget, {"planner": "strong", "worker": "cheap"}, default_model="fake"
    )
    return router, gateway, redis


def test_roles_are_mapped_to_models(sessions: sessionmaker[Session]) -> None:
    router, gateway, _ = build(sessions, "0.01")
    for role in (Role.PLANNER, Role.WORKER, Role.TEST_WRITER, Role.REVIEWER):
        router.chat(role, [{"role": "user", "content": "x"}])
    assert gateway.calls == [
        ("strong", "planner"),
        ("cheap", "worker"),
        ("fake", "test-writer"),  # not configured: default model
        ("fake", "reviewer"),
    ]


def test_hard_cap_pauses_the_project_and_publishes_budget_reached(
    sessions: sessionmaker[Session],
) -> None:
    router, gateway, redis = build(sessions, "0.50")
    project = make_project(sessions, "1.00")
    messages = [{"role": "user", "content": "x"}]

    router.chat(Role.WORKER, messages, project_id=project)
    assert status(sessions, project) == "active"
    router.chat(Role.WORKER, messages, project_id=project)  # reaches 1.00
    assert status(sessions, project) == "paused"
    assert event_types(redis).count("budget.reached") == 1

    with pytest.raises(BudgetExceeded):
        router.chat(Role.WORKER, messages, project_id=project)
    assert len(gateway.calls) == 2, "no LLM call once the cap is hit"
    assert event_types(redis).count("budget.reached") == 1, "published once only"

    _, fields = next(e for e in redis.added if e[1]["type"] == "budget.reached")
    assert str(project) in fields["payload"]


def test_warning_at_80_percent_is_published_once(sessions: sessionmaker[Session]) -> None:
    router, _, redis = build(sessions, "0.40")
    project = make_project(sessions, "1.00")
    messages = [{"role": "user", "content": "x"}]
    router.chat(Role.WORKER, messages, project_id=project)  # 0.40
    assert event_types(redis) == []
    router.chat(Role.WORKER, messages, project_id=project)  # 0.80
    router.chat(Role.WORKER, messages, project_id=project)  # 1.20 -> reached
    types = event_types(redis)
    assert types.count("budget.warning") == 1
    assert types.count("budget.reached") == 1
    assert types.index("budget.warning") < types.index("budget.reached")


def test_projects_without_budget_and_calls_without_project_are_unlimited(
    sessions: sessionmaker[Session],
) -> None:
    router, gateway, redis = build(sessions, "100")
    project = make_project(sessions, None)
    messages = [{"role": "user", "content": "x"}]
    for _ in range(3):
        router.chat(Role.WORKER, messages, project_id=project)
        router.chat(Role.WORKER, messages)
    assert len(gateway.calls) == 6
    assert status(sessions, project) == "active"
    assert event_types(redis) == []


def test_raising_the_budget_resumes_a_paused_project(sessions: sessionmaker[Session]) -> None:
    router, _, _ = build(sessions, "1.00")
    project = make_project(sessions, "1.00")
    router.chat(Role.WORKER, [{"role": "user", "content": "x"}], project_id=project)
    assert status(sessions, project) == "paused"

    with sessions() as session:
        row = session.get(Project, project)
        assert row is not None
        apply_budget(session, row, Decimal("1.00"))  # not above the spend: stays paused
        session.commit()
    assert status(sessions, project) == "paused"

    with sessions() as session:
        row = session.get(Project, project)
        assert row is not None
        apply_budget(session, row, Decimal("3.00"))
        session.commit()
    assert status(sessions, project) == "active"
    router.chat(Role.WORKER, [{"role": "user", "content": "x"}], project_id=project)
