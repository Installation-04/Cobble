from __future__ import annotations

import json
import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from cobble.api.app import create_app
from cobble.auth.sessions import create_session
from cobble.config import Settings
from cobble.db import Message, Plan, Project, Spec, User
from cobble.events import JOBS_STREAM, project_stream

from .fakes import FakeStreamRedis
from .planning import events_of, load_script, make_project

H = {"X-Requested-With": "cobble"}
API = "/api/v1"
ESTIMATE = {
    "tokens": 30000,
    "cost_usd": "0.06",
    "milestones": [{"id": "M1", "tokens": 30000, "cost_usd": "0.06"}],
}


@pytest.fixture
def redis() -> FakeStreamRedis:
    return FakeStreamRedis()


def client_for(
    sessions: sessionmaker[Session], redis: FakeStreamRedis, user_id: uuid.UUID
) -> TestClient:
    app = create_app(
        {"database": lambda: None, "redis": lambda: None},
        settings=Settings(),
        session_factory=sessions,
        redis=redis,
    )
    client = TestClient(app)
    with sessions() as db:
        client.cookies.set("cobble_session", create_session(db, user_id))
    return client


def owner_of(sessions: sessionmaker[Session], pid: uuid.UUID) -> uuid.UUID:
    with sessions() as db:
        project = db.get(Project, pid)
        assert project is not None
        return project.owner_id


@pytest.fixture
def pid(sessions: sessionmaker[Session]) -> uuid.UUID:
    return make_project(sessions)


@pytest.fixture
def api(sessions: sessionmaker[Session], redis: FakeStreamRedis, pid: uuid.UUID) -> TestClient:
    return client_for(sessions, redis, owner_of(sessions, pid))


def set_phase(sessions: sessionmaker[Session], pid: uuid.UUID, phase: str, **fields: Any) -> None:
    with sessions() as db:
        project = db.get(Project, pid)
        assert project is not None
        project.phase = phase
        for name, value in fields.items():
            setattr(project, name, value)
        db.commit()


def add_spec(
    sessions: sessionmaker[Session], pid: uuid.UUID, status: str, version: int = 1
) -> None:
    with sessions() as db:
        db.add(Spec(project_id=pid, version=version, content=f"# Spec {version}", status=status))
        db.commit()


def add_plan(sessions: sessionmaker[Session], pid: uuid.UUID, version: int = 1) -> None:
    with sessions() as db:
        db.add(
            Plan(
                project_id=pid,
                version=version,
                plan=load_script().valid_plan("en"),
                estimate=ESTIMATE,
            )
        )
        db.commit()


def code(reply: Any) -> str:
    return reply.json()["error"]["code"]


def jobs(redis: FakeStreamRedis) -> list[dict[str, Any]]:
    return [json.loads(e["job"]) for e in redis.entries(JOBS_STREAM)]


# --- auth and ownership --------------------------------------------------------------------

ENDPOINTS = [
    ("GET", "/messages"),
    ("POST", "/messages"),
    ("POST", "/spec/generate"),
    ("GET", "/spec"),
    ("POST", "/spec/approve"),
    ("POST", "/plan/generate"),
    ("GET", "/plan"),
    ("POST", "/plan/approve"),
    ("GET", "/stream"),
]


@pytest.mark.parametrize(("method", "path"), ENDPOINTS)
def test_every_endpoint_needs_a_session(
    sessions: sessionmaker[Session], redis: FakeStreamRedis, pid: uuid.UUID, method: str, path: str
) -> None:
    app = create_app(
        {"database": lambda: None}, settings=Settings(), session_factory=sessions, redis=redis
    )
    reply = TestClient(app).request(
        method, f"{API}/projects/{pid}{path}", json={"content": "x"}, headers=H
    )
    assert reply.status_code == 401
    assert code(reply) == "unauthenticated"


@pytest.mark.parametrize(("method", "path"), ENDPOINTS)
def test_other_users_projects_are_not_found(
    sessions: sessionmaker[Session], redis: FakeStreamRedis, pid: uuid.UUID, method: str, path: str
) -> None:
    with sessions() as db:
        eve = User(email="eve@example.com", password_hash="x")
        db.add(eve)
        db.commit()
        eve_id = eve.id
    reply = client_for(sessions, redis, eve_id).request(
        method, f"{API}/projects/{pid}{path}", json={"content": "x"}, headers=H
    )
    assert reply.status_code == 404
    assert code(reply) == "not_found"
    assert redis.entries(JOBS_STREAM) == []


@pytest.mark.parametrize(("method", "path"), ENDPOINTS)
def test_malformed_and_unknown_project_ids_are_not_found(
    api: TestClient, method: str, path: str
) -> None:
    for ghost in ("not-a-uuid", str(uuid.uuid4())):
        reply = api.request(
            method, f"{API}/projects/{ghost}{path}", json={"content": "x"}, headers=H
        )
        assert reply.status_code == 404


@pytest.mark.parametrize(
    "path", ["/messages", "/spec/generate", "/spec/approve", "/plan/generate", "/plan/approve"]
)
def test_unsafe_methods_need_the_csrf_header(api: TestClient, pid: uuid.UUID, path: str) -> None:
    assert api.post(f"{API}/projects/{pid}{path}", json={"content": "x"}).status_code == 403


def test_project_exposes_its_phase(api: TestClient, pid: uuid.UUID) -> None:
    created = api.post(f"{API}/projects", json={"name": "Fresh"}, headers=H).json()
    assert created["phase"] == "interview"
    listed = api.get(f"{API}/projects").json()
    assert {p["phase"] for p in listed} == {"interview"}


# --- interview -----------------------------------------------------------------------------


def test_posting_a_message_stores_it_enqueues_a_reply_and_publishes(
    api: TestClient, redis: FakeStreamRedis, pid: uuid.UUID
) -> None:
    reply = api.post(
        f"{API}/projects/{pid}/messages", json={"content": "  I want a to-do app "}, headers=H
    )
    assert reply.status_code == 202
    message = reply.json()["message"]
    assert message["role"] == "user"
    assert message["content"] == "I want a to-do app"
    assert set(message) == {"id", "role", "content", "created_at"}

    assert jobs(redis) == [{"kind": "reply", "project_id": str(pid), "message_id": message["id"]}]
    events = events_of(redis, pid)
    assert [name for name, _ in events] == ["message.created"]
    assert events[0][1]["message"]["id"] == message["id"]


def test_messages_are_listed_oldest_first(
    api: TestClient, sessions: sessionmaker[Session], pid: uuid.UUID
) -> None:
    assert api.get(f"{API}/projects/{pid}/messages").json() == []
    api.post(f"{API}/projects/{pid}/messages", json={"content": "one"}, headers=H)
    with sessions() as db:
        db.add(Message(project_id=pid, role="assistant", content="two"))
        db.commit()
    api.post(f"{API}/projects/{pid}/messages", json={"content": "three"}, headers=H)
    listed = api.get(f"{API}/projects/{pid}/messages").json()
    assert [(m["role"], m["content"]) for m in listed] == [
        ("user", "one"),
        ("assistant", "two"),
        ("user", "three"),
    ]


@pytest.mark.parametrize("content", ["", "   ", "x" * 8001])
def test_message_length_is_validated(
    api: TestClient, redis: FakeStreamRedis, pid: uuid.UUID, content: str
) -> None:
    reply = api.post(f"{API}/projects/{pid}/messages", json={"content": content}, headers=H)
    assert reply.status_code == 422
    assert code(reply) == "validation_error"
    assert redis.entries(JOBS_STREAM) == []


def test_message_of_8000_characters_is_accepted(api: TestClient, pid: uuid.UUID) -> None:
    reply = api.post(f"{API}/projects/{pid}/messages", json={"content": "x" * 8000}, headers=H)
    assert reply.status_code == 202


def test_messages_are_refused_outside_the_interview(
    api: TestClient, sessions: sessionmaker[Session], redis: FakeStreamRedis, pid: uuid.UUID
) -> None:
    set_phase(sessions, pid, "spec_review")
    reply = api.post(f"{API}/projects/{pid}/messages", json={"content": "hi"}, headers=H)
    assert reply.status_code == 409
    assert code(reply) == "wrong_phase"
    assert redis.entries(JOBS_STREAM) == []
    assert api.get(f"{API}/projects/{pid}/messages").json() == []


def test_a_paused_project_refuses_every_generation(
    api: TestClient, sessions: sessionmaker[Session], redis: FakeStreamRedis, pid: uuid.UUID
) -> None:
    set_phase(sessions, pid, "interview", status="paused")
    reply = api.post(f"{API}/projects/{pid}/messages", json={"content": "hi"}, headers=H)
    assert (reply.status_code, code(reply)) == (409, "project_paused")
    reply = api.post(f"{API}/projects/{pid}/spec/generate", headers=H)
    assert (reply.status_code, code(reply)) == (409, "project_paused")

    add_spec(sessions, pid, "approved")
    set_phase(sessions, pid, "spec_review", status="paused")
    reply = api.post(f"{API}/projects/{pid}/plan/generate", headers=H)
    assert (reply.status_code, code(reply)) == (409, "project_paused")
    assert redis.entries(JOBS_STREAM) == []


def test_queue_failure_is_a_503(sessions: sessionmaker[Session], pid: uuid.UUID) -> None:
    api = client_for(sessions, FakeStreamRedis(fail=True), owner_of(sessions, pid))
    reply = api.post(f"{API}/projects/{pid}/spec/generate", headers=H)
    assert (reply.status_code, code(reply)) == (503, "queue_unavailable")


# --- spec ----------------------------------------------------------------------------------


@pytest.mark.parametrize("phase", ["interview", "spec_review"])
@pytest.mark.parametrize(
    ("body", "feedback"),
    [
        (None, None),
        ({}, None),
        ({"feedback": "  "}, None),
        ({"feedback": " add dark mode "}, "add dark mode"),
    ],
)
def test_spec_generation_is_enqueued(
    api: TestClient,
    sessions: sessionmaker[Session],
    redis: FakeStreamRedis,
    pid: uuid.UUID,
    phase: str,
    body: dict[str, Any] | None,
    feedback: str | None,
) -> None:
    set_phase(sessions, pid, phase)
    reply = api.post(f"{API}/projects/{pid}/spec/generate", json=body, headers=H)
    assert reply.status_code == 202
    assert reply.json() == {}
    assert jobs(redis) == [{"kind": "spec", "project_id": str(pid), "feedback": feedback}]


@pytest.mark.parametrize("phase", ["plan_review", "ready"])
def test_spec_generation_is_refused_after_the_spec_phase(
    api: TestClient, sessions: sessionmaker[Session], pid: uuid.UUID, phase: str
) -> None:
    set_phase(sessions, pid, phase)
    reply = api.post(f"{API}/projects/{pid}/spec/generate", headers=H)
    assert (reply.status_code, code(reply)) == (409, "wrong_phase")


def test_get_spec_returns_the_latest_version(
    api: TestClient, sessions: sessionmaker[Session], pid: uuid.UUID
) -> None:
    assert api.get(f"{API}/projects/{pid}/spec").status_code == 404
    add_spec(sessions, pid, "draft", 1)
    add_spec(sessions, pid, "draft", 2)
    body = api.get(f"{API}/projects/{pid}/spec").json()
    assert (body["version"], body["content"], body["status"]) == (2, "# Spec 2", "draft")
    assert "created_at" in body


def test_approve_spec(
    api: TestClient, sessions: sessionmaker[Session], redis: FakeStreamRedis, pid: uuid.UUID
) -> None:
    assert api.post(f"{API}/projects/{pid}/spec/approve", headers=H).status_code == 404
    add_spec(sessions, pid, "draft")
    reply = api.post(f"{API}/projects/{pid}/spec/approve", headers=H)
    assert (reply.status_code, code(reply)) == (409, "wrong_phase")  # still in the interview

    set_phase(sessions, pid, "spec_review")
    reply = api.post(f"{API}/projects/{pid}/spec/approve", headers=H)
    assert reply.status_code == 200
    assert reply.json()["status"] == "approved"
    assert api.get(f"{API}/projects/{pid}/spec").json()["status"] == "approved"
    assert events_of(redis, pid) == [("spec.updated", {"version": 1})]
    # Approving again changes nothing and publishes nothing.
    assert api.post(f"{API}/projects/{pid}/spec/approve", headers=H).status_code == 200
    assert len(events_of(redis, pid)) == 1


# --- plan ----------------------------------------------------------------------------------


def test_plan_generation_needs_an_approved_spec_in_review(
    api: TestClient, sessions: sessionmaker[Session], redis: FakeStreamRedis, pid: uuid.UUID
) -> None:
    reply = api.post(f"{API}/projects/{pid}/plan/generate", headers=H)
    assert (reply.status_code, code(reply)) == (409, "wrong_phase")  # interview

    set_phase(sessions, pid, "spec_review")
    reply = api.post(f"{API}/projects/{pid}/plan/generate", headers=H)
    assert (reply.status_code, code(reply)) == (409, "wrong_phase")  # no spec

    add_spec(sessions, pid, "draft")
    reply = api.post(f"{API}/projects/{pid}/plan/generate", headers=H)
    assert (reply.status_code, code(reply)) == (409, "wrong_phase")  # not approved
    assert redis.entries(JOBS_STREAM) == []


def test_plan_generation_is_enqueued_with_feedback(
    api: TestClient, sessions: sessionmaker[Session], redis: FakeStreamRedis, pid: uuid.UUID
) -> None:
    add_spec(sessions, pid, "approved")
    set_phase(sessions, pid, "spec_review")
    assert api.post(f"{API}/projects/{pid}/plan/generate", headers=H).status_code == 202
    set_phase(sessions, pid, "plan_review")
    reply = api.post(
        f"{API}/projects/{pid}/plan/generate", json={"feedback": "smaller tasks"}, headers=H
    )
    assert reply.status_code == 202
    assert jobs(redis) == [
        {"kind": "plan", "project_id": str(pid), "feedback": None},
        {"kind": "plan", "project_id": str(pid), "feedback": "smaller tasks"},
    ]


def test_get_plan_returns_plan_and_estimate(
    api: TestClient, sessions: sessionmaker[Session], pid: uuid.UUID
) -> None:
    assert api.get(f"{API}/projects/{pid}/plan").status_code == 404
    add_plan(sessions, pid, 1)
    add_plan(sessions, pid, 2)
    body = api.get(f"{API}/projects/{pid}/plan").json()
    assert (body["version"], body["status"]) == (2, "draft")
    assert body["estimate"] == ESTIMATE
    assert len(body["plan"]["tasks"]) == 11
    assert "created_at" in body


def test_approving_the_plan_moves_the_project_to_ready(
    api: TestClient, sessions: sessionmaker[Session], redis: FakeStreamRedis, pid: uuid.UUID
) -> None:
    assert api.post(f"{API}/projects/{pid}/plan/approve", headers=H).status_code == 404
    add_plan(sessions, pid)
    add_spec(sessions, pid, "approved")
    reply = api.post(f"{API}/projects/{pid}/plan/approve", headers=H)
    assert (reply.status_code, code(reply)) == (409, "wrong_phase")

    set_phase(sessions, pid, "plan_review")
    reply = api.post(f"{API}/projects/{pid}/plan/approve", headers=H)
    assert reply.status_code == 200
    assert reply.json()["status"] == "approved"
    assert api.get(f"{API}/projects").json()[0]["phase"] == "ready"
    assert events_of(redis, pid) == [
        ("plan.updated", {"version": 1}),
        ("phase.changed", {"phase": "ready"}),
    ]
    # Once ready, nothing can be generated or approved any more.
    for path in ("/messages", "/spec/generate", "/plan/generate", "/plan/approve", "/spec/approve"):
        again = api.post(f"{API}/projects/{pid}{path}", json={"content": "x"}, headers=H)
        assert again.status_code == 409


def test_project_stream_name_matches_the_adr(pid: uuid.UUID) -> None:
    assert project_stream(pid) == f"cobble:project:{pid}:events"
