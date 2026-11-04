"""Confidential projects: nothing leaves this machine, and when unsure nothing is sent."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from cobble.capabilities.llm import ChatResult, Role
from cobble.db import Base, Project, User, make_session_factory
from cobble.router.costs import CostRouter, LocalOnlyUnavailable
from cobble.router.gateway import GatewayError
from cobble.router.local import LocalModels, project_is_local_only

PROJECT = uuid.uuid4()


class Gateway:
    def __init__(self, failures: dict[str, Exception] | None = None) -> None:
        self.failures = failures or {}
        self.tried: list[str] = []

    def chat(self, model: str, messages: list[dict[str, Any]], **kw: Any) -> ChatResult:
        self.tried.append(model)
        if model in self.failures:
            raise self.failures[model]
        return ChatResult("ok", model, 1, 1, Decimal("0"), None)


class Budget:
    def ensure_can_spend(self, project_id: Any) -> None: ...
    def after_call(self, project_id: Any) -> None: ...


def router(
    gateway: Gateway,
    chain: list[str],
    *,
    local_only: bool = True,
    local: set[str] | None = None,
    no_lookup: bool = False,
) -> CostRouter:
    return CostRouter(  # type: ignore[arg-type]
        gateway,
        Budget(),
        {},
        "default",
        chain_for=lambda role: list(chain),
        is_local_only=lambda project_id: local_only,
        local_models=None if no_lookup else (lambda: local or set()),
    )


def test_a_confidential_project_only_reaches_models_served_here() -> None:
    gateway = Gateway()
    result = router(gateway, ["paid-api", "coder"], local={"coder"}).chat(
        Role.WORKER, [], project_id=PROJECT
    )
    assert result.model == "coder" and gateway.tried == ["coder"]  # the paid one is never asked


def test_the_escalation_model_cannot_send_a_confidential_project_outside() -> None:
    gateway = Gateway()
    r = router(gateway, ["coder"], local={"coder"})
    r.chat(
        Role.WORKER, [], project_id=PROJECT, model="strong-api"
    )  # escalation asks for a paid model
    assert gateway.tried == ["coder"]


def test_with_no_local_model_the_call_is_refused_before_anything_is_sent() -> None:
    gateway = Gateway()
    for kwargs in ({"local": set()}, {"no_lookup": True}):
        with pytest.raises(LocalOnlyUnavailable):
            router(gateway, ["paid-api"], **kwargs).chat(Role.PLANNER, [], project_id=PROJECT)  # type: ignore[arg-type]
    assert gateway.tried == []


def test_local_fallbacks_still_work_inside_a_confidential_project() -> None:
    gateway = Gateway({"coder": GatewayError(503)})
    result = router(gateway, ["paid", "coder", "coder-small"], local={"coder", "coder-small"}).chat(
        Role.WORKER, [], project_id=PROJECT
    )
    assert result.model == "coder-small" and gateway.tried == ["coder", "coder-small"]


def test_an_ordinary_project_or_a_call_without_a_project_is_not_restricted() -> None:
    gateway = Gateway()
    r = router(gateway, ["paid-api"], local_only=False, local={"coder"})
    assert r.chat(Role.WORKER, [], project_id=PROJECT).model == "paid-api"
    confidential = router(gateway, ["paid-api"], local={"coder"})
    assert confidential.chat(Role.WORKER, []).model == "paid-api"  # no project: nothing to protect


# --- which models are local, which projects are confidential -----------------------------------


def test_local_models_are_read_once_per_ttl_and_a_failure_means_none() -> None:
    now = [0.0]
    asked: list[int] = []
    answers: list[Any] = [{"local": [{"name": "coder"}]}, RuntimeError("down")]

    def fetch() -> dict[str, Any]:
        asked.append(1)
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer  # type: ignore[no-any-return]

    local = LocalModels(fetch, ttl_s=10, clock=lambda: now[0])
    assert local() == {"coder"} and local() == {"coder"} and len(asked) == 1
    now[0] = 11
    assert local() == set()  # the manager went away: no model is known to be local


def test_a_malformed_listing_is_no_local_model() -> None:
    assert LocalModels(lambda: {"local": "nope"})() == set()
    assert LocalModels(lambda: {"local": [{"model": "x"}]})() == set()


@pytest.fixture
def sessions() -> Any:
    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    yield make_session_factory(engine)
    engine.dispose()


def test_the_project_flag_is_read_and_an_unreadable_project_counts_as_confidential(
    sessions: sessionmaker[Session],
) -> None:
    with sessions() as db:
        owner = User(email="a@b.co", password_hash="x", role="admin")
        db.add(owner)
        db.flush()
        db.add_all(
            [
                Project(id=PROJECT, owner_id=owner.id, name="secret", local_only=True),
                Project(id=(other := uuid.uuid4()), owner_id=owner.id, name="open"),
            ]
        )
        db.commit()
    check = project_is_local_only(sessions)
    assert check(PROJECT) is True and check(other) is False
    assert check(uuid.uuid4()) is False  # no such project: nothing to protect

    class Broken:
        def __call__(self) -> Any:
            raise OperationalError("select", {}, Exception("down"))

    assert project_is_local_only(Broken())(PROJECT) is True  # type: ignore[arg-type]
