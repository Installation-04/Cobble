from __future__ import annotations

import json
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from cobble.api.app import create_app
from cobble.auth.sessions import create_session
from cobble.config import Settings
from cobble.db import Project
from cobble.events import JOBS_STREAM
from cobble.worker import make_job_handler

from .fakes import FakeStreamRedis
from .planning import events_of
from .scheduling import Harness, make_ready_project

H = {"X-Requested-With": "cobble"}
API = "/api/v1"


@pytest.fixture
def redis() -> FakeStreamRedis:
    return FakeStreamRedis()


def client_for(
    sessions: sessionmaker[Session], redis: FakeStreamRedis, project_id: uuid.UUID
) -> TestClient:
    app = create_app(
        {"database": lambda: None, "redis": lambda: None},
        settings=Settings(),
        session_factory=sessions,
        redis=redis,
    )
    client = TestClient(app)
    with sessions() as db:
        project = db.get(Project, project_id)
        assert project is not None
        client.cookies.set("cobble_session", create_session(db, project.owner_id))
    return client


@pytest.fixture
def pid(sessions: sessionmaker[Session]) -> uuid.UUID:
    return make_ready_project(sessions)


@pytest.fixture
def api(sessions: sessionmaker[Session], redis: FakeStreamRedis, pid: uuid.UUID) -> TestClient:
    return client_for(sessions, redis, pid)


def queued(redis: FakeStreamRedis) -> list[dict[str, object]]:
    return [json.loads(e["job"]) for e in redis.entries(JOBS_STREAM)]


def test_start_queues_a_start_job(api: TestClient, redis: FakeStreamRedis, pid: uuid.UUID) -> None:
    response = api.post(f"{API}/projects/{pid}/start", headers=H)
    assert response.status_code == 202
    assert queued(redis) == [{"kind": "start", "project_id": str(pid)}]


def test_start_requires_csrf_and_login(
    sessions: sessionmaker[Session], redis: FakeStreamRedis, pid: uuid.UUID, api: TestClient
) -> None:
    assert api.post(f"{API}/projects/{pid}/start").status_code == 403
    anonymous = TestClient(
        create_app(
            {"database": lambda: None, "redis": lambda: None},
            settings=Settings(),
            session_factory=sessions,
            redis=redis,
        )
    )
    response = anonymous.post(f"{API}/projects/{pid}/start", headers=H)
    assert response.status_code == 401
    assert queued(redis) == []


@pytest.mark.parametrize("phase", ["interview", "spec_review", "plan_review", "building", "done"])
def test_start_needs_the_ready_phase(
    sessions: sessionmaker[Session], redis: FakeStreamRedis, phase: str
) -> None:
    project = make_ready_project(sessions, phase=phase)
    api = client_for(sessions, redis, project)
    response = api.post(f"{API}/projects/{project}/start", headers=H)
    assert response.status_code == 409
    assert response.json() == {"error": {"code": "wrong_phase", "params": {"phase": phase}}}
    assert queued(redis) == []


def test_start_refuses_a_paused_project(
    api: TestClient, sessions: sessionmaker[Session], redis: FakeStreamRedis, pid: uuid.UUID
) -> None:
    with sessions() as db:
        project = db.get(Project, pid)
        assert project is not None
        project.status = "paused"
        db.commit()
    response = api.post(f"{API}/projects/{pid}/start", headers=H)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "project_paused"
    assert queued(redis) == []


def test_start_reports_a_down_queue(sessions: sessionmaker[Session], pid: uuid.UUID) -> None:
    api = client_for(sessions, FakeStreamRedis(fail=True), pid)
    response = api.post(f"{API}/projects/{pid}/start", headers=H)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "queue_unavailable"


def test_other_users_cannot_start_or_see_tasks(
    sessions: sessionmaker[Session], redis: FakeStreamRedis, pid: uuid.UUID
) -> None:
    stranger = client_for(sessions, redis, make_ready_project(sessions))
    assert stranger.post(f"{API}/projects/{pid}/start", headers=H).status_code == 404
    assert stranger.get(f"{API}/projects/{pid}/tasks").status_code == 404
    assert stranger.get(f"{API}/projects/{pid}/tasks/T-001").status_code == 404


def test_worker_job_starts_the_project_then_tasks_are_listed(
    sessions: sessionmaker[Session], redis: FakeStreamRedis, pid: uuid.UUID, api: TestClient
) -> None:
    harness = Harness(sessions, redis=redis)
    assert api.get(f"{API}/projects/{pid}/tasks").json() == []

    assert api.post(f"{API}/projects/{pid}/start", headers=H).status_code == 202
    handler = make_job_handler(None, harness.scheduler)  # type: ignore[arg-type]
    handler({b"job": redis.entries(JOBS_STREAM)[0]["job"].encode()})
    assert api.get(f"{API}/projects").json()[0]["phase"] == "building"

    tasks = api.get(f"{API}/projects/{pid}/tasks").json()
    assert [t["ref"] for t in tasks] == [f"T-{n:03d}" for n in range(1, 12)]
    assert tasks[2] == {
        "ref": "T-003",
        "title": "Create and list todos",
        "milestone": "M1",
        "state": "todo",
        "attempts": 0,
        "escalated": False,
        "role": "backend",
        "size": "M",
        "depends_on": ["T-002"],
    }
    types = [t for t, _ in events_of(redis, pid)]
    assert types == ["job.started", "phase.changed", "project.building"]


def test_start_job_without_a_scheduler_reports_it(
    sessions: sessionmaker[Session], redis: FakeStreamRedis, pid: uuid.UUID
) -> None:
    handler = make_job_handler(None, None, redis)  # type: ignore[arg-type]
    handler({b"job": json.dumps({"kind": "start", "project_id": str(pid)}).encode()})
    assert events_of(redis, pid) == [
        ("job.failed", {"kind": "start", "code": "scheduler_unavailable"})
    ]


def test_task_detail_lists_its_runs(
    sessions: sessionmaker[Session], redis: FakeStreamRedis, pid: uuid.UUID, api: TestClient
) -> None:
    harness = Harness(sessions, redis=redis)
    harness.start(pid)
    harness.run_until(pid)
    detail = api.get(f"{API}/projects/{pid}/tasks/T-002")
    assert detail.status_code == 200
    body = detail.json()
    assert body["state"] == "merged"
    assert body["attempts"] == 1
    assert body["depends_on"] == ["T-001"]
    assert [(r["kind"], r["attempt"], r["state"], r["model"]) for r in body["runs"]] == [
        ("test-writer", 1, "done", "cheap"),
        ("worker", 1, "done", "cheap"),
    ]
    run = body["runs"][1]
    assert set(run) == {
        "kind",
        "attempt",
        "model",
        "state",
        "started_at",
        "finished_at",
        "iterations",
        "log_tail",
    }
    assert run["iterations"] == 1
    assert run["finished_at"] is not None
    assert run["log_tail"].startswith("fake log of run-")
    assert api.get(f"{API}/projects").json()[0]["phase"] == "done"


def test_unknown_task_is_not_found(api: TestClient, pid: uuid.UUID) -> None:
    response = api.get(f"{API}/projects/{pid}/tasks/T-999")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
