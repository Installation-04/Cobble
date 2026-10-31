"""Logs, diff and the four controls over HTTP (ADR 0007)."""

from __future__ import annotations

import uuid

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from cobble.api.app import create_app
from cobble.auth.sessions import create_session
from cobble.capabilities.agent import AgentUnavailable
from cobble.capabilities.fakes import FakeAgentRunner
from cobble.capabilities.git import DIFF_LIMIT
from cobble.config import Settings
from cobble.db import Project, Task, TaskRun

from .fakes import FakeStreamRedis
from .planning import events_of
from .scheduling import Harness, make_ready_project

H = {"X-Requested-With": "cobble"}
API = "/api/v1"


class Env:
    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self.sessions = sessions
        self.redis = FakeStreamRedis()
        self.pid = make_ready_project(sessions)
        self.harness = Harness(
            sessions, agents=FakeAgentRunner(polls_before_done=1000), redis=self.redis
        )
        self.harness.start(self.pid)
        self.harness.scheduler.tick()  # T-001 is writing its tests
        self.app = create_app(
            {"database": lambda: None, "redis": lambda: None},
            settings=Settings(),
            session_factory=sessions,
            redis=self.redis,
        )
        self.app.state.agents = self.harness.agents
        self.app.state.git = self.harness.git
        self.client = self.login(self.pid)

    def login(self, project_id: uuid.UUID) -> TestClient:
        client = TestClient(self.app)
        with self.sessions() as db:
            project = db.get(Project, project_id)
            assert project is not None
            client.cookies.set("cobble_session", create_session(db, project.owner_id))
        return client


@pytest.fixture
def env(sessions: sessionmaker[Session]) -> Env:
    return Env(sessions)


def url(env: Env, ref: str, tail: str) -> str:
    return f"{API}/projects/{env.pid}/tasks/{ref}/{tail}"


# --- logs ---------------------------------------------------------------------------------


def test_logs_come_from_the_agent_runner_with_a_next_offset(env: Env) -> None:
    response = env.client.get(url(env, "T-001", "logs"))
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert response.text.startswith("fake log of run-1\n$ test-writer on task/t-001\n")
    total = int(response.headers["X-Next-Offset"])
    assert total == len(response.text)

    tail = env.client.get(url(env, "T-001", "logs"), params={"offset": 10})
    assert tail.text == response.text[10:]
    assert tail.headers["X-Next-Offset"] == str(total)
    empty = env.client.get(url(env, "T-001", "logs"), params={"offset": total})
    assert (empty.text, empty.headers["X-Next-Offset"]) == ("", str(total))


def test_logs_fall_back_to_the_stored_tail(env: Env) -> None:
    with env.sessions() as db:
        run = db.scalars(select(TaskRun)).one()
        run.log_tail = "stored tail of the run"
        db.commit()
    env.harness.agents.unavailable = True
    response = env.client.get(url(env, "T-001", "logs"), params={"offset": 7})
    assert (response.status_code, response.text) == (200, "tail of the run")
    assert response.headers["X-Next-Offset"] == str(len("stored tail of the run"))
    # An offset beyond the tail never moves backwards.
    far = env.client.get(url(env, "T-001", "logs"), params={"offset": 500})
    assert (far.text, far.headers["X-Next-Offset"]) == ("", "500")


def test_logs_fall_back_when_the_service_forgot_the_run_or_is_absent(env: Env) -> None:
    with env.sessions() as db:
        run = db.scalars(select(TaskRun)).one()
        run.log_tail = "tail"
        db.commit()
    env.harness.agents.lost.add("run-1")
    assert env.client.get(url(env, "T-001", "logs")).text == "tail"
    env.harness.agents.lost.clear()
    env.app.state.agents = None  # and no pack configured: the lazy build yields nothing
    env.app.state.pack_services = None
    assert env.client.get(url(env, "T-001", "logs")).text == "tail"


def test_logs_of_a_task_that_never_ran_are_empty(env: Env) -> None:
    response = env.client.get(url(env, "T-003", "logs"))
    assert (response.status_code, response.text, response.headers["X-Next-Offset"]) == (
        200,
        "",
        "0",
    )


def test_logs_reject_a_negative_offset(env: Env) -> None:
    response = env.client.get(url(env, "T-001", "logs"), params={"offset": -1})
    assert response.status_code == 422


# --- diff ---------------------------------------------------------------------------------


def test_diff_is_empty_before_the_first_push(env: Env) -> None:
    assert env.client.get(url(env, "T-003", "diff")).json() == {"diff": "", "truncated": False}


def test_diff_of_the_task_branch(env: Env) -> None:
    repo = env.harness.repo_ref(env.pid)
    env.harness.git.diffs[(repo.name, "task/t-001")] = "diff --git a/x b/x\n+hello\n"
    response = env.client.get(url(env, "T-001", "diff"))
    assert response.status_code == 200
    assert response.json() == {"diff": "diff --git a/x b/x\n+hello\n", "truncated": False}
    assert env.harness.git.diff_calls == [(repo.name, "main", "task/t-001", None)]


def test_diff_is_capped_and_flagged(env: Env) -> None:
    repo = env.harness.repo_ref(env.pid)
    env.harness.git.diffs[(repo.name, "task/t-001")] = ("+" + "x" * 99 + "\n") * 5000
    body = env.client.get(url(env, "T-001", "diff")).json()
    assert body["truncated"] is True
    assert len(body["diff"]) <= DIFF_LIMIT
    assert body["diff"].endswith("\n")


def test_diff_uses_the_merge_request_number_once_there_is_one(env: Env) -> None:
    with env.sessions() as db:
        task = db.scalars(select(Task).where(Task.ref == "T-001")).one()
        task.pr_number = 12
        db.commit()
    env.client.get(url(env, "T-001", "diff"))
    assert env.harness.git.diff_calls[-1][3] == 12


def test_diff_reports_a_missing_or_failing_git_provider(env: Env) -> None:
    env.app.state.git = None
    env.app.state.pack_services = None
    response = env.client.get(url(env, "T-001", "diff"))
    assert (response.status_code, response.json()["error"]["code"]) == (503, "git_unavailable")

    class Broken:
        def diff(self, *_a: object, **_k: object) -> tuple[str, bool]:
            raise RuntimeError("secret detail")

    env.app.state.git = Broken()
    response = env.client.get(url(env, "T-001", "diff"))
    assert response.status_code == 503
    assert "secret" not in response.text


# --- controls -----------------------------------------------------------------------------


def task_state(env: Env, ref: str) -> str:
    return env.harness.states(env.pid)[ref]


def test_pause_resume_round_trip_returns_the_task_and_publishes(env: Env) -> None:
    paused = env.client.post(url(env, "T-001", "pause"), headers=H)
    assert paused.status_code == 200
    body = paused.json()
    assert body["ref"] == "T-001"
    assert body["state"] == "paused"
    assert set(body) == {
        "ref",
        "title",
        "milestone",
        "state",
        "attempts",
        "escalated",
        "role",
        "size",
        "depends_on",
    }
    assert env.client.post(url(env, "T-001", "pause"), headers=H).json()["state"] == "paused"
    resumed = env.client.post(url(env, "T-001", "resume"), headers=H)
    assert resumed.json()["state"] == "writing_tests"
    states = [p["state"] for t, p in events_of(env.redis, env.pid) if t == "task.updated"]
    assert states[-2:] == ["paused", "writing_tests"]


def test_stop_then_retry(env: Env) -> None:
    stopped = env.client.post(url(env, "T-001", "stop"), headers=H)
    assert (stopped.status_code, stopped.json()["state"]) == (200, "stopped")
    assert env.harness.agents.stopped == ["run-1"]
    retried = env.client.post(url(env, "T-001", "retry"), headers=H)
    assert (retried.status_code, retried.json()["state"]) == (200, "todo")
    assert retried.json()["attempts"] == 0


def test_wrong_state_is_a_409(env: Env) -> None:
    response = env.client.post(url(env, "T-001", "retry"), headers=H)  # still running
    assert response.status_code == 409
    assert response.json() == {
        "error": {"code": "wrong_state", "params": {"state": "writing_tests"}}
    }
    assert task_state(env, "T-001") == "writing_tests"
    env.client.post(url(env, "T-001", "stop"), headers=H)
    assert env.client.post(url(env, "T-001", "resume"), headers=H).status_code == 409
    assert env.client.post(url(env, "T-001", "pause"), headers=H).status_code == 409


def test_stop_with_an_unreachable_agent_service_changes_nothing(env: Env) -> None:
    class Down(FakeAgentRunner):
        def stop(self, run_id: str) -> None:
            raise AgentUnavailable("down")

    env.app.state.agents = Down()
    response = env.client.post(url(env, "T-001", "stop"), headers=H)
    assert (response.status_code, response.json()["error"]["code"]) == (503, "agent_unavailable")
    assert task_state(env, "T-001") == "writing_tests"
    env.app.state.agents = None
    env.app.state.pack_services = None
    assert env.client.post(url(env, "T-001", "stop"), headers=H).status_code == 503
    assert task_state(env, "T-001") == "writing_tests"


@pytest.mark.parametrize("tail", ["pause", "resume", "stop", "retry"])
def test_controls_need_csrf_and_login_and_ownership(env: Env, tail: str) -> None:
    assert env.client.post(url(env, "T-001", tail)).status_code == 403
    anonymous = TestClient(env.app)
    assert anonymous.post(url(env, "T-001", tail), headers=H).status_code == 401
    stranger = env.login(make_ready_project(env.sessions))
    assert stranger.post(url(env, "T-001", tail), headers=H).status_code == 404
    assert env.client.post(url(env, "T-999", tail), headers=H).status_code == 404
    assert task_state(env, "T-001") == "writing_tests"


@pytest.mark.parametrize("tail", ["logs", "diff"])
def test_reads_need_login_and_ownership(env: Env, tail: str) -> None:
    assert TestClient(env.app).get(url(env, "T-001", tail)).status_code == 401
    stranger = env.login(make_ready_project(env.sessions))
    assert stranger.get(url(env, "T-001", tail)).status_code == 404
    assert env.client.get(url(env, "T-999", tail)).status_code == 404
    assert env.client.get(f"{API}/projects/not-a-uuid/tasks/T-001/{tail}").status_code == 404


def test_the_real_http_runner_is_used_through_the_same_endpoint(env: Env) -> None:
    from cobble.providers.agent_service import HttpAgentRunner

    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, text="line\n", headers={"X-Next-Offset": "5"})

    env.app.state.agents = HttpAgentRunner(
        "http://agents:8080", "t", transport=httpx.MockTransport(handler)
    )
    response = env.client.get(url(env, "T-001", "logs"), params={"offset": 2})
    assert (response.text, response.headers["X-Next-Offset"]) == ("line\n", "5")
    assert seen[0].url.path == "/v1/runs/run-1/logs"
