"""Which model answers: the platform's choice if there is one, else the configured one."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from cobble.capabilities.llm import ChatResult, Role
from cobble.config import Settings
from cobble.db.models import PlatformState
from cobble.router.costs import CostRouter
from cobble.router.policy import ModelPolicy


def choose(sessions: sessionmaker[Session], model: str | None) -> None:
    with sessions() as db:
        state = db.get(PlatformState, 1) or PlatformState(id=1)
        state.default_model = model
        db.add(state)
        db.commit()


def test_without_a_choice_the_configured_default_applies(
    sessions: sessionmaker[Session],
) -> None:
    policy = ModelPolicy(sessions, Settings(default_model="fake"))
    assert policy.default() == "fake"
    assert policy.model_for(Role.PLANNER) == "fake"


def test_the_choice_made_in_the_product_wins_and_applies_at_once(
    sessions: sessionmaker[Session],
) -> None:
    policy = ModelPolicy(sessions, Settings(default_model="fake"))
    choose(sessions, "cheap")
    assert policy.default() == "cheap" and policy.model_for(Role.WORKER) == "cheap"
    choose(sessions, "better")  # no restart: the next call sees it
    assert policy.default() == "better"
    choose(sessions, None)
    assert policy.default() == "fake"


def test_a_role_pinned_in_the_configuration_keeps_its_model(
    sessions: sessionmaker[Session],
) -> None:
    policy = ModelPolicy(sessions, Settings(role_models={"planner": "strong"}))
    choose(sessions, "cheap")
    assert policy.model_for(Role.PLANNER) == "strong"
    assert policy.model_for(Role.WORKER) == "cheap"


def test_a_database_hiccup_falls_back_instead_of_failing_every_call() -> None:
    class Broken:
        def __call__(self) -> Any:
            raise OperationalError("select", {}, Exception("down"))

    policy = ModelPolicy(Broken(), Settings(default_model="fake"))  # type: ignore[arg-type]
    assert policy.default() == "fake"


class Recorder:
    def __init__(self) -> None:
        self.models: list[str] = []

    def chat(self, model: str, messages: list[dict[str, Any]], **kw: Any) -> ChatResult:
        self.models.append(model)
        return ChatResult("ok", model, 1, 1, Decimal("0"), None)


class NoBudget:
    def ensure_can_spend(self, project_id: Any) -> None: ...
    def after_call(self, project_id: Any) -> None: ...


def test_the_cost_router_follows_the_default_as_it_changes(
    sessions: sessionmaker[Session],
) -> None:
    gateway = Recorder()
    policy = ModelPolicy(sessions, Settings(default_model="fake"))
    router = CostRouter(gateway, NoBudget(), {}, policy.default)  # type: ignore[arg-type]
    router.chat(Role.PLANNER, [{"role": "user", "content": "hi"}])
    choose(sessions, "cheap")
    router.chat(Role.PLANNER, [{"role": "user", "content": "hi"}])
    assert gateway.models == ["fake", "cheap"]


def test_a_plain_string_default_still_works() -> None:
    gateway = Recorder()
    router = CostRouter(gateway, NoBudget(), {"worker": "w"}, "fixed")  # type: ignore[arg-type]
    router.chat(Role.PLANNER, [])
    router.chat(Role.WORKER, [])
    assert gateway.models == ["fixed", "w"]
