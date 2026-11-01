"""The browser-facing model connections API, wired through the real client to the real service."""

from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from cobble.module_manager.connections import ConnectionStore
from cobble.module_manager.redaction import Redactor
from cobble.module_manager.vault import Vault
from cobble.providers.module_manager import HttpModuleManager
from cobble.router.gateway import ProbeResult

from .test_model_connections import Gateway
from .test_module_manager import MASTER, OLLAMA, Rig
from .test_module_service import TOKEN
from .test_modules_api import H, Stack

API = "/api/v1/models"
KEY = "sk-api-do-not-leak-98765432100123"
BODY = {"provider": "openai", "model": "gpt-4.1-mini", "api_key": KEY}


class Probe:
    def __init__(self) -> None:
        self.asked: list[str] = []
        self.result = ProbeResult(True, "ok")

    def probe(self, model: str) -> ProbeResult:
        self.asked.append(model)
        return self.result


class Built:
    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self.gateway = Gateway()
        rig = Rig(
            modules=[OLLAMA],
            llm=self.gateway,
            connections=ConnectionStore(Vault({1: MASTER}), Redactor()),
        )
        self.stack = Stack(sessions, rig)
        self.probe = Probe()
        self.api: TestClient = self.stack.api
        self.api.app.state.gateway = self.probe  # type: ignore[attr-defined]
        self.stack.login(self.api)


@pytest.fixture
def built(sessions: sessionmaker[Session]) -> Built:
    return Built(sessions)


ROUTES = [
    ("GET", API),
    ("PUT", f"{API}/cheap"),
    ("DELETE", f"{API}/cheap"),
    ("POST", f"{API}/cheap/default"),
    ("POST", f"{API}/cheap/test"),
]


@pytest.mark.parametrize(("method", "path"), ROUTES)
def test_anonymous_users_are_turned_away(
    sessions: sessionmaker[Session], method: str, path: str
) -> None:
    b = Built(sessions)
    b.api.cookies.clear()
    reply = b.api.request(method, path, json=BODY if method == "PUT" else None, headers=H)
    assert reply.status_code == 401
    assert b.stack.requests == []


@pytest.mark.parametrize(("method", "path"), ROUTES)
def test_only_administrators_may_connect_models(
    sessions: sessionmaker[Session], method: str, path: str
) -> None:
    b = Built(sessions)
    b.api.cookies.clear()
    b.stack.login(b.api, role="member")
    reply = b.api.request(method, path, json=BODY if method == "PUT" else None, headers=H)
    assert reply.status_code == 403 and reply.json()["error"]["code"] == "forbidden"
    assert b.stack.requests == [] and b.probe.asked == []


@pytest.mark.parametrize(("method", "path"), ROUTES[1:])
def test_changes_need_the_csrf_header(built: Built, method: str, path: str) -> None:
    reply = built.api.request(method, path, json=BODY if method == "PUT" else None)
    assert reply.status_code == 403 and reply.json()["error"]["code"] == "csrf_failed"
    assert built.stack.requests == []


def test_a_model_is_connected_and_the_key_comes_back_nowhere(built: Built) -> None:
    empty = built.api.get(API).json()
    assert empty == {"models": [], "default": None, "configured_default": "fake"}
    reply = built.api.put(f"{API}/cheap", json=BODY, headers=H)
    assert reply.status_code == 200
    assert reply.json()["default"] == "cheap" and reply.json()["configured_default"] == "fake"
    assert [m["name"] for m in reply.json()["models"]] == ["cheap"]
    everything = reply.text + built.api.get(API).text
    assert KEY not in everything and "api_key" not in everything
    assert built.gateway.last[0].api_key == KEY


def test_a_bad_request_names_the_fields_without_echoing_the_key(built: Built) -> None:
    reply = built.api.put(f"{API}/Bad Name", json={**BODY, "provider": "skynet"}, headers=H)
    assert reply.status_code == 422
    assert reply.json()["error"]["code"] == "invalid_request"
    assert KEY not in reply.text
    reply = built.api.put(f"{API}/x", json={"api_key": KEY}, headers=H)  # fields missing
    assert reply.status_code == 422 and KEY not in reply.text


def test_a_gateway_failure_is_reported_as_such_not_as_an_unavailable_manager(
    built: Built,
) -> None:
    built.gateway.fail = True
    reply = built.api.put(f"{API}/cheap", json=BODY, headers=H)
    assert reply.status_code == 502
    assert reply.json()["error"]["code"] == "model_gateway_failed"
    assert KEY not in reply.text
    built.gateway.fail = False
    assert built.api.get(API).json()["models"] == []  # nothing was kept


def test_the_default_can_be_changed_and_a_model_removed(built: Built) -> None:
    built.api.put(f"{API}/first", json=BODY, headers=H)
    built.api.put(f"{API}/second", json=BODY, headers=H)
    assert built.api.post(f"{API}/second/default", headers=H).json()["default"] == "second"
    after = built.api.delete(f"{API}/second", headers=H).json()
    assert after["default"] is None and after["configured_default"] == "fake"
    assert [m["name"] for m in after["models"]] == ["first"]


def test_unknown_models_are_404(built: Built) -> None:
    for method, path in (
        ("POST", f"{API}/ghost/default"),
        ("DELETE", f"{API}/ghost"),
        ("POST", f"{API}/ghost/test"),
    ):
        reply = built.api.request(method, path, headers=H)
        assert reply.status_code == 404 and reply.json()["error"]["code"] == "model_unknown", path
    assert built.probe.asked == []  # an unknown name is never sent to the gateway


def test_a_connection_is_tested_through_the_gateway_with_a_stable_code(built: Built) -> None:
    built.api.put(f"{API}/cheap", json=BODY, headers=H)
    assert built.api.post(f"{API}/cheap/test", headers=H).json() == {"ok": True, "code": "ok"}
    built.probe.result = ProbeResult(False, "auth_failed")
    reply = built.api.post(f"{API}/cheap/test", headers=H)
    assert reply.json() == {"ok": False, "code": "auth_failed"}
    assert built.probe.asked == ["cheap", "cheap"] and KEY not in reply.text


def test_a_model_change_during_a_module_operation_is_busy(built: Built) -> None:
    with built.stack.service.rig.manager._lock:
        reply = built.api.put(f"{API}/cheap", json=BODY, headers=H)
    assert reply.status_code == 409 and reply.json()["error"]["code"] == "module_busy"


def test_an_unreachable_module_manager_is_a_503(built: Built) -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    manager = HttpModuleManager("http://mm", TOKEN, transport=httpx.MockTransport(refuse))
    built.api.app.state.module_manager = manager  # type: ignore[attr-defined]
    for method, path in (("GET", API), ("PUT", f"{API}/x")):
        reply = built.api.request(method, path, json=BODY if method == "PUT" else None, headers=H)
        assert reply.status_code == 503, path
        assert reply.json()["error"]["code"] == "module_manager_unavailable"


def test_a_client_that_gets_a_5xx_without_a_refusal_code_says_unavailable() -> None:
    def broken(request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, json={"error": {"code": "something_else", "params": {}}})

    from cobble.providers.module_manager import ModuleManagerUnavailable

    client = HttpModuleManager("http://mm", TOKEN, transport=httpx.MockTransport(broken))
    with pytest.raises(ModuleManagerUnavailable):
        client.models()


def test_a_model_change_may_take_as_long_as_a_gateway_restart() -> None:
    """The first real run found the API giving up after 20 s while the manager was still
    restarting the gateway (and then completing the change)."""
    from cobble.providers.module_manager import GATEWAY_CHANGE_TIMEOUT_S

    timeouts: dict[str, float] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        timeouts[f"{request.method} {request.url.path}"] = request.extensions["timeout"]["read"]
        return httpx.Response(200, json={"models": [], "default": None})

    client = HttpModuleManager("http://mm", TOKEN, transport=httpx.MockTransport(handler))
    client.put_model("x", {"provider": "openai"})
    client.delete_model("x")
    client.set_default_model("x")
    client.models()
    assert timeouts["PUT /v1/models/x"] == GATEWAY_CHANGE_TIMEOUT_S >= 300
    assert timeouts["DELETE /v1/models/x"] == GATEWAY_CHANGE_TIMEOUT_S
    assert timeouts["POST /v1/models/x/default"] == 20.0  # no restart: the usual wait is enough
    assert timeouts["GET /v1/models"] == 20.0
