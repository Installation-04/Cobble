from __future__ import annotations

import json
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from cobble.capabilities.fakes_preview import FakePreviewProvider
from cobble.config import Settings
from cobble.events import JOBS_STREAM, project_stream
from cobble.worker import make_job_handler

from .fakes import FakeStreamRedis
from .planning import events_of
from .scheduling import Harness, make_ready_project
from .test_scheduler_demo import build_all, milestones
from .test_tasks_api import API, H, client_for


@pytest.fixture
def redis() -> FakeStreamRedis:
    return FakeStreamRedis()


@pytest.fixture
def pid(sessions: sessionmaker[Session]) -> uuid.UUID:
    return make_ready_project(sessions)


@pytest.fixture
def h(sessions: sessionmaker[Session], redis: FakeStreamRedis) -> Harness:
    return Harness(sessions, preview=FakePreviewProvider(), redis=redis)


@pytest.fixture
def api(
    sessions: sessionmaker[Session], redis: FakeStreamRedis, pid: uuid.UUID, h: Harness
) -> TestClient:
    return client_for(sessions, redis, pid)


def url(pid: uuid.UUID, ref: str = "", action: str = "") -> str:
    base = f"{API}/projects/{pid}/milestones"
    return f"{base}/{ref}/{action}" if ref else base


def test_list_milestones(api: TestClient, h: Harness, pid: uuid.UUID) -> None:
    assert api.get(url(pid)).json() == []
    h.start(pid)
    body = api.get(url(pid)).json()
    assert [m["ref"] for m in body] == ["M1", "M2", "M3"]
    assert body[0] == {
        "ref": "M1",
        "title": body[0]["title"],
        "status": "pending",
        "tag": None,
        "preview_path": None,
        "preview_state": None,
        "built_at": None,
        "validated_at": None,
    }


def test_validate_and_wrong_state(api: TestClient, h: Harness, pid: uuid.UUID) -> None:
    h.start(pid)
    early = api.post(url(pid, "M1", "validate"), headers=H)
    assert early.status_code == 409
    assert early.json() == {"error": {"code": "wrong_state", "params": {}}}
    for _ in range(300):
        h.scheduler.tick()
        if milestones(h, pid)["M1"].status == "built":
            break
    response = api.post(url(pid, "M1", "validate"), headers=H)
    assert response.status_code == 200
    milestone = response.json()["milestone"]
    assert milestone["status"] == "validated" and milestone["validated_at"]
    assert milestone["preview_path"] == f"/demo/{pid}/M1/"
    assert ("milestone.updated", "validated") in [
        (t, p.get("status")) for t, p in events_of(h.redis, pid)
    ]
    assert api.post(url(pid, "M9", "validate"), headers=H).status_code == 404


def test_comment_creates_a_task_and_reopens(api: TestClient, h: Harness, pid: uuid.UUID) -> None:
    build_all(h, pid)
    response = api.post(url(pid, "M2", "comments"), headers=H, json={"content": "  Bigger font  "})
    assert response.status_code == 201
    task = response.json()["task"]
    assert (task["ref"], task["state"], task["milestone"]) == ("C-001", "todo", "M2")
    assert h.phase(pid) == "building"
    assert api.get(url(pid)).json()[1]["status"] == "pending"
    assert (
        api.post(url(pid, "M2", "comments"), headers=H, json={"content": "again"}).status_code
        == 409
    )
    for bad in ("", "   ", "x" * 2001):
        r = api.post(url(pid, "M1", "comments"), headers=H, json={"content": bad})
        assert r.status_code == 422, bad


def test_revert_queues_a_job_and_the_worker_runs_it(
    api: TestClient, h: Harness, redis: FakeStreamRedis, pid: uuid.UUID
) -> None:
    h.start(pid)
    assert api.post(url(pid, "M1", "revert"), headers=H).status_code == 409
    build_all(h, pid)
    response = api.post(url(pid, "M2", "revert"), headers=H)
    assert (response.status_code, response.json()) == (202, {})
    (job,) = [json.loads(e["job"]) for e in redis.entries(JOBS_STREAM)]
    assert job == {"kind": "revert", "project_id": str(pid), "ref": "M2"}
    handler = make_job_handler(None, h.scheduler)  # type: ignore[arg-type]
    handler({b"job": json.dumps(job).encode()})
    states = {m["ref"]: m["status"] for m in api.get(url(pid)).json()}
    assert states == {"M1": "validated", "M2": "pending", "M3": "pending"}
    assert project_stream(pid)


def test_demo_endpoints_are_owner_scoped_and_need_csrf(
    sessions: sessionmaker[Session], redis: FakeStreamRedis, pid: uuid.UUID, api: TestClient
) -> None:
    other = make_ready_project(sessions)
    stranger = client_for(sessions, redis, other)
    assert stranger.get(url(pid)).status_code == 404
    assert stranger.post(url(pid, "M1", "validate"), headers=H).status_code == 404
    assert api.post(url(pid, "M1", "validate")).status_code == 403
    assert api.post(url(pid, "M1", "revert")).status_code == 403
    assert settings_ok()


def settings_ok() -> bool:
    return Settings().pack_mode == "real"
