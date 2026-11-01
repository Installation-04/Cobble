"""The browser-facing modules API, wired through the real client to the real service app."""

from __future__ import annotations

import re
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from cobble.api.app import create_app
from cobble.api.sse import SseOptions
from cobble.auth.sessions import create_session
from cobble.config import Settings
from cobble.db import User
from cobble.events import MODULE_STREAM, publish_module
from cobble.providers.module_manager import HttpModuleManager

from .fakes import FakeStreamRedis
from .test_module_manager import FORGEJO, GITEA, WOODPECKER, Rig
from .test_module_service import TOKEN, Service

H = {"X-Requested-With": "cobble"}
API = "/api/v1/modules"
ROOT = Path(__file__).resolve().parents[3]


class Stack:
    """API -> HttpModuleManager -> (in memory) -> the module-manager's own app."""

    def __init__(self, sessions: sessionmaker[Session], rig: Rig | None = None) -> None:
        self.service = Service(rig or Rig(), defer=False)
        self.requests: list[httpx.Request] = []
        service_client = self.service.client

        def forward(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            reply = service_client.request(
                request.method,
                request.url.path,
                content=request.content,
                headers={k: v for k, v in request.headers.items() if k != "host"},
            )
            return httpx.Response(reply.status_code, content=reply.content, headers=reply.headers)

        self.redis = FakeStreamRedis()
        self.sessions = sessions
        self.api = self._client(
            HttpModuleManager("http://mm", TOKEN, transport=httpx.MockTransport(forward))
        )

    def _client(self, manager: HttpModuleManager) -> TestClient:
        app = create_app(
            {"database": lambda: None, "redis": lambda: None},
            settings=Settings(),
            session_factory=self.sessions,
            redis=self.redis,
        )
        app.state.module_manager = manager
        app.state.sse = SseOptions(ping_s=0.05, block_ms=5, max_s=0.3)
        return TestClient(app)

    def login(self, client: TestClient, role: str = "admin") -> TestClient:
        with self.sessions() as db:
            user = User(email=f"{role}-{id(client)}@example.com", password_hash="x", role=role)
            db.add(user)
            db.commit()
            client.cookies.set("cobble_session", create_session(db, user.id))
        return client


@pytest.fixture
def stack(sessions: sessionmaker[Session]) -> Stack:
    built = Stack(sessions)
    built.login(built.api)
    return built


# --- who may use it ---------------------------------------------------------------------------

ROUTES = [
    ("GET", f"{API}"),
    ("POST", f"{API}/plan"),
    ("POST", f"{API}/operations"),
    ("GET", f"{API}/operations/abc"),
    ("GET", f"{API}/stream"),
    ("GET", f"{API}/forgejo/secrets"),
]
BODY = {"action": "install", "modules": ["forgejo"]}


@pytest.mark.parametrize(("method", "path"), ROUTES)
def test_anonymous_users_are_turned_away(
    sessions: sessionmaker[Session], method: str, path: str
) -> None:
    built = Stack(sessions)
    reply = built.api.request(method, path, json=BODY if method == "POST" else None, headers=H)
    assert reply.status_code == 401
    assert reply.json()["error"]["code"] == "unauthenticated"
    assert built.requests == []  # nothing reached the module-manager


@pytest.mark.parametrize(("method", "path"), ROUTES)
def test_only_administrators_may_use_the_store(
    sessions: sessionmaker[Session], method: str, path: str
) -> None:
    built = Stack(sessions)
    built.login(built.api, role="member")
    reply = built.api.request(method, path, json=BODY if method == "POST" else None, headers=H)
    assert reply.status_code == 403
    assert reply.json()["error"]["code"] == "forbidden"
    assert built.requests == []


def test_unsafe_requests_need_the_csrf_header(stack: Stack) -> None:
    reply = stack.api.post(f"{API}/operations", json=BODY)
    assert reply.status_code == 403
    assert reply.json()["error"]["code"] == "csrf_failed"
    assert stack.requests == []


# --- the happy path, end to end ---------------------------------------------------------------


def test_list_plan_install_and_follow_the_operation(stack: Stack) -> None:
    catalog = stack.api.get(API).json()
    assert {m["id"] for m in catalog["modules"]} == {"forgejo", "woodpecker"}

    plan = stack.api.post(
        f"{API}/plan", json={"action": "install", "modules": ["woodpecker"]}, headers=H
    )
    assert plan.status_code == 200
    assert [s["module"] for s in plan.json()["steps"]] == ["forgejo", "woodpecker"]

    started = stack.api.post(
        f"{API}/operations", json={"action": "install", "modules": ["woodpecker"]}, headers=H
    )
    assert started.status_code == 202
    operation = stack.api.get(f"{API}/operations/{started.json()['operation_id']}").json()
    assert operation["state"] == "done"
    assert set(stack.service.rig.modules()) == {"forgejo", "woodpecker"}

    secrets = stack.api.get(f"{API}/forgejo/secrets")
    assert secrets.json() == {"admin_password": True, "api_token": True}


def test_the_service_token_is_sent_and_never_shown_to_the_browser(stack: Stack) -> None:
    reply = stack.api.get(API)
    assert stack.requests[-1].headers["authorization"] == f"Bearer {TOKEN}"
    assert TOKEN not in reply.text
    assert "authorization" not in {k.lower() for k in reply.headers}


# --- the manager's refusals reach the browser with their data ---------------------------------


def test_choices_and_cascades_come_back_as_questions(sessions: sessionmaker[Session]) -> None:
    built = Stack(sessions, Rig([FORGEJO, GITEA, WOODPECKER]))
    built.login(built.api)
    ask = built.api.post(
        f"{API}/plan", json={"action": "install", "modules": ["woodpecker"]}, headers=H
    )
    assert ask.status_code == 409
    assert ask.json() == {
        "error": {
            "code": "module_needs_choice",
            "params": {"capability": "git", "candidates": ["forgejo", "gitea"]},
        }
    }
    chosen = {"action": "install", "modules": ["woodpecker"], "choices": {"git": "gitea"}}
    assert built.api.post(f"{API}/operations", json=chosen, headers=H).status_code == 202
    cascade = built.api.post(
        f"{API}/plan", json={"action": "uninstall", "modules": ["gitea"]}, headers=H
    )
    assert cascade.status_code == 409
    assert cascade.json()["error"]["code"] == "module_needs_confirmation"
    assert cascade.json()["error"]["params"] == {"cascade": ["woodpecker"]}
    unknown = built.api.post(
        f"{API}/plan", json={"action": "install", "modules": ["nope"]}, headers=H
    )
    assert unknown.status_code == 404
    assert unknown.json()["error"]["params"] == {"module": "nope"}


def test_a_second_operation_while_one_runs_is_busy(sessions: sessionmaker[Session]) -> None:
    built = Stack(sessions)
    built.login(built.api)
    built.service.controller._spawn = lambda job: built.service.deferred.append(job)
    assert built.api.post(f"{API}/operations", json=BODY, headers=H).status_code == 202
    busy = built.api.post(
        f"{API}/operations", json={"action": "install", "modules": ["woodpecker"]}, headers=H
    )
    assert busy.status_code == 409
    assert busy.json()["error"]["code"] == "module_busy"


def test_invalid_bodies_are_rejected_before_the_manager_is_called(stack: Stack) -> None:
    for body in ({"action": "install", "modules": []}, {"action": "boom", "modules": ["a"]}, {}):
        reply = stack.api.post(f"{API}/plan", json=body, headers=H)
        assert reply.status_code == 422
        assert reply.json()["error"]["code"] == "validation_error"
    assert stack.requests == []


# --- when the module-manager is not there -----------------------------------------------------


@pytest.mark.parametrize(
    "failure",
    [
        httpx.ConnectError("refused"),
        httpx.ReadTimeout("slow"),
    ],
)
def test_an_unreachable_manager_is_a_503_that_leaks_nothing(
    sessions: sessionmaker[Session], failure: Exception
) -> None:
    def broken(request: httpx.Request) -> httpx.Response:
        raise failure

    built = Stack(sessions)
    built.api = built._client(
        HttpModuleManager("http://mm", "secret-token-xyz", transport=httpx.MockTransport(broken))
    )
    built.login(built.api)
    reply = built.api.get(API)
    assert reply.status_code == 503
    assert reply.json() == {"error": {"code": "module_manager_unavailable", "params": {}}}
    assert "secret-token-xyz" not in reply.text


@pytest.mark.parametrize("status", [401, 403, 500, 502])
def test_a_rejected_token_or_a_server_error_is_also_unavailable(
    sessions: sessionmaker[Session], status: int
) -> None:
    built = Stack(sessions)
    built.api = built._client(
        HttpModuleManager(
            "http://mm",
            "t",
            # what the real service answers: a JSON error body, not an empty response
            transport=httpx.MockTransport(
                lambda r: httpx.Response(
                    status, json={"error": {"code": "unauthorized", "params": {}}}
                )
            ),
        )
    )
    built.login(built.api)
    reply = built.api.post(f"{API}/operations", json=BODY, headers=H)
    assert reply.status_code == 503
    assert reply.json()["error"]["code"] == "module_manager_unavailable"


def test_an_unreadable_answer_is_unavailable(sessions: sessionmaker[Session]) -> None:
    built = Stack(sessions)
    built.api = built._client(
        HttpModuleManager(
            "http://mm",
            "t",
            transport=httpx.MockTransport(lambda r: httpx.Response(200, text="<html>")),
        )
    )
    built.login(built.api)
    assert built.api.get(API).status_code == 503


# --- progress stream --------------------------------------------------------------------------


def test_the_progress_stream_replays_from_a_cursor_and_only_for_administrators(
    stack: Stack,
) -> None:
    publish_module(stack.redis, "module.step", {"operation_id": "o1", "module": "forgejo"})  # type: ignore[arg-type]
    publish_module(stack.redis, "module.operation", {"operation_id": "o1", "state": "done"})  # type: ignore[arg-type]
    reply = stack.api.get(f"{API}/stream", headers={"Last-Event-ID": "1-0"})
    assert reply.status_code == 200
    assert reply.headers["content-type"].startswith("text/event-stream")
    assert "id: 2-0\nevent: module.operation\n" in reply.text
    assert "module.step" not in reply.text
    everything = stack.api.get(f"{API}/stream?last_event_id=0-0")
    assert "event: module.step" in everything.text
    assert MODULE_STREAM == "cobble:modules:events"


# --- every code the user can see is translated ------------------------------------------------


def _locale(lang: str) -> dict[str, str]:
    import json

    return json.loads((ROOT / "ui" / "src" / "locales" / lang / "errors.json").read_text("utf-8"))  # type: ignore[no-any-return]


def _literal_codes(*files: str, pattern: str) -> set[str]:
    found: set[str] = set()
    for name in files:
        text = (ROOT / "backend" / "cobble" / name).read_text("utf-8")
        found |= set(re.findall(pattern, text))
    return found


def test_every_refusal_and_failure_code_has_a_translation_in_both_languages() -> None:
    refusals = _literal_codes(
        "module_manager/app.py", pattern=r'"(module_[a-z_]+|invalid_request)"'
    )
    step_codes = _literal_codes(
        "module_manager/runner.py",
        "module_manager/vault.py",
        "module_manager/manager.py",
        pattern=r'(?:RunnerError|VaultError)\("([a-z_]+)"\)',
    ) | {"no_compatible_variant", "compose_rejected", "internal_error"}
    # These only happen while the service starts (it then refuses to run and logs the code): they
    # can never be the result of an operation, so the user never sees them.
    start_up_only = {
        "bad_master_key",
        "no_master_key",
        "key_file_unreadable",
        "key_file_permissions",
        "key_file_exists",
    }
    step_codes -= start_up_only
    api_codes = {"forbidden", "module_manager_unavailable"}
    for lang in ("en", "fr"):
        messages = _locale(lang)
        missing = [c for c in refusals | api_codes if c not in messages]
        missing += [f"module_code_{c}" for c in step_codes if f"module_code_{c}" not in messages]
        assert missing == [], f"{lang}: untranslated {missing}"
        assert "module_code_unknown" in messages
