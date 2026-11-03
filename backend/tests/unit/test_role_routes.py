"""Per-role routes with fallback chains: which models, in which order, and when to move on."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import httpx
import pytest
from sqlalchemy.orm import Session, sessionmaker

from cobble.capabilities.llm import ChatResult, Role
from cobble.config import Settings
from cobble.db.models import PlatformState
from cobble.router.costs import CostRouter, can_fall_back
from cobble.router.gateway import GatewayError
from cobble.router.policy import MAX_CHAIN, ROLES, ModelPolicy


def route(
    sessions: sessionmaker[Session], routes: dict[str, list[str]] | None, **state: Any
) -> None:
    with sessions() as db:
        row = db.get(PlatformState, 1) or PlatformState(id=1)
        row.role_routes = routes
        for key, value in state.items():
            setattr(row, key, value)
        db.add(row)
        db.commit()


def test_without_routes_every_role_follows_the_default(sessions: sessionmaker[Session]) -> None:
    policy = ModelPolicy(sessions, Settings(default_model="fake"))
    for role in ROLES:
        assert policy.chain_for(role) == ["fake"] or role is Role.ESCALATION
    assert policy.chain_for(Role.ESCALATION) == ["fake"]  # no route, no setting: the planner's
    assert policy.routes() == {}


def test_a_route_set_in_the_product_orders_the_models_and_applies_at_once(
    sessions: sessionmaker[Session],
) -> None:
    policy = ModelPolicy(sessions, Settings(default_model="fake", role_models={"worker": "pinned"}))
    assert policy.chain_for(Role.WORKER) == ["pinned"]
    route(sessions, {"worker": ["local", "cheap", "strong"]})
    assert policy.chain_for(Role.WORKER) == ["local", "cheap", "strong"]  # beats the setting
    assert policy.model_for(Role.WORKER) == "local"
    assert policy.chain_for(Role.PLANNER) == ["fake"]  # other roles are untouched
    route(sessions, {"worker": []})  # an emptied route is no route
    assert policy.chain_for(Role.WORKER) == ["pinned"]
    route(sessions, None)
    assert policy.routes() == {}


def test_a_chain_has_no_duplicates_and_is_bounded(sessions: sessionmaker[Session]) -> None:
    route(sessions, {"worker": ["a", "b", "a", "c", "d", "e", "f"]})
    chain = ModelPolicy(sessions, Settings()).chain_for(Role.WORKER)
    assert chain == ["a", "b", "c", "d"] and len(chain) == MAX_CHAIN


def test_escalation_is_its_own_route_then_the_setting_then_the_planner(
    sessions: sessionmaker[Session],
) -> None:
    policy = ModelPolicy(sessions, Settings(default_model="d", escalation_model="env-strong"))
    assert policy.chain_for(Role.ESCALATION) == ["env-strong"]
    route(sessions, {"planner": ["plan-a", "plan-b"]})
    assert policy.chain_for(Role.ESCALATION) == ["env-strong"]
    route(sessions, {"planner": ["plan-a", "plan-b"], "escalation": ["big"]})
    assert policy.chain_for(Role.ESCALATION) == ["big"]
    plain = ModelPolicy(sessions, Settings(default_model="d"))
    route(sessions, {"planner": ["plan-a", "plan-b"]})
    assert plain.chain_for(Role.ESCALATION) == ["plan-a", "plan-b"]


# --- the router --------------------------------------------------------------------------------


class Gateway:
    def __init__(self, failures: dict[str, Exception] | None = None) -> None:
        self.failures = failures or {}
        self.tried: list[str] = []
        self.recorded: list[tuple[str, str | None, int]] = []  # (answered, fallback_from, count)

    def chat(self, model: str, messages: list[dict[str, Any]], **kw: Any) -> ChatResult:
        self.tried.append(model)
        if model not in self.failures:
            self.recorded.append((model, kw.get("fallback_from"), kw.get("fallbacks", 0)))
        if model in self.failures:
            raise self.failures[model]
        return ChatResult("ok", model, 1, 1, Decimal("0"), None)


class Budget:
    def __init__(self) -> None:
        self.checked = 0

    def ensure_can_spend(self, project_id: Any) -> None:
        self.checked += 1

    def after_call(self, project_id: Any) -> None: ...


def router(gateway: Gateway, chains: dict[str, list[str]]) -> CostRouter:
    return CostRouter(  # type: ignore[arg-type]
        gateway, Budget(), {}, "default", chain_for=lambda role: chains.get(role.value, ["default"])
    )


@pytest.mark.parametrize("status", [401, 402, 403, 404, 408, 429, 500, 502, 503])
def test_a_model_that_cannot_answer_hands_over_to_the_next_one(status: int) -> None:
    gateway = Gateway({"local": GatewayError(status)})
    result = router(gateway, {"worker": ["local", "cheap", "strong"]}).chat(Role.WORKER, [])
    assert result.model == "cheap" and gateway.tried == ["local", "cheap"]


def test_an_unreachable_service_also_hands_over() -> None:
    gateway = Gateway({"local": httpx.ConnectError("down")})
    assert router(gateway, {"worker": ["local", "cheap"]}).chat(Role.WORKER, []).model == "cheap"


def test_a_request_the_service_rejects_is_not_retried_elsewhere() -> None:
    gateway = Gateway({"local": GatewayError(400)})
    with pytest.raises(GatewayError):
        router(gateway, {"worker": ["local", "cheap"]}).chat(Role.WORKER, [])
    assert gateway.tried == ["local"]  # the same request would fail the same way, and cost more


def test_when_every_model_fails_the_last_error_is_raised() -> None:
    gateway = Gateway({"a": GatewayError(429), "b": GatewayError(503)})
    with pytest.raises(GatewayError) as info:
        router(gateway, {"worker": ["a", "b"]}).chat(Role.WORKER, [])
    assert info.value.status == 503 and gateway.tried == ["a", "b"]


def test_an_explicit_model_goes_first_and_the_chain_follows_without_repeating_it() -> None:
    gateway = Gateway({"big": GatewayError(429)})
    result = router(gateway, {"worker": ["local", "big", "cheap"]}).chat(
        Role.WORKER, [], model="big"
    )
    assert gateway.tried == ["big", "local"] and result.model == "local"


def test_the_budget_is_checked_once_whatever_the_number_of_fallbacks() -> None:
    gateway = Gateway({"a": GatewayError(500)})
    r = router(gateway, {"worker": ["a", "b"]})
    r.chat(Role.WORKER, [], project_id=__import__("uuid").uuid4())
    assert r._budget.checked == 1  # type: ignore[attr-defined]


def test_which_errors_allow_a_fallback() -> None:
    assert can_fall_back(GatewayError(429)) and can_fall_back(httpx.ReadTimeout("slow"))
    assert not can_fall_back(GatewayError(400)) and not can_fall_back(ValueError("bug"))


def test_the_answering_call_says_which_model_it_fell_back_from() -> None:
    gateway = Gateway({"a": GatewayError(429), "b": GatewayError(503)})
    router(gateway, {"worker": ["a", "b", "c"]}).chat(Role.WORKER, [])
    assert gateway.recorded == [("c", "a", 2)]  # the first that failed, and how many failed
    clean = Gateway()
    router(clean, {"worker": ["a", "b"]}).chat(Role.WORKER, [])
    assert clean.recorded == [("a", None, 0)]  # no fallback: nothing recorded


def test_a_model_the_gateway_does_not_know_hands_over_but_a_plain_bad_request_does_not() -> None:
    gone = Gateway({"removed": GatewayError(400, unknown_model=True)})
    assert router(gone, {"worker": ["removed", "cheap"]}).chat(Role.WORKER, []).model == "cheap"
    assert can_fall_back(GatewayError(400, unknown_model=True))
    assert not can_fall_back(GatewayError(400))
