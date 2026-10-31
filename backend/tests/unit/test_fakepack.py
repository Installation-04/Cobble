"""The fake pack: a stateless simulated runner, the factory switch, the demo page."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from cobble.api.app import create_app
from cobble.capabilities.agent import AgentOutcome, AgentRunNotFound, AgentTask
from cobble.capabilities.git import RepoRef
from cobble.capabilities.llm import Role
from cobble.config import Settings
from cobble.scheduler import demo
from cobble.scheduler.factory import build_scheduler
from cobble.scheduler.fakepack import SimulatedAgentRunner, StatelessFakeGit

from .fakes import FakeStreamRedis
from .scheduling import make_ready_project, make_settings


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def task(role: Role = Role.WORKER) -> AgentTask:
    return AgentTask(
        task_id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        repo_clone_url="fake://x.git",
        branch="task/t-001",
        role=role,
        instructions="x",
        marker="[cobble-task:T-001:worker:1]",
    )


def test_runs_take_steps_and_are_stateless() -> None:
    clock = Clock()
    worker = SimulatedAgentRunner(0.5, clock=clock)
    run_id = worker.start(task())
    other_process = SimulatedAgentRunner(0.5, clock=clock)  # knows nothing of the worker
    assert other_process.poll(run_id) is None
    text, offset = other_process.logs(run_id)
    assert "task/t-001" in text and offset == len(text)
    clock.now += 1.0
    more, offset2 = other_process.logs(run_id, offset)
    assert offset2 > offset and more == other_process.logs(run_id)[0][offset:]
    assert other_process.poll(run_id) is None
    assert "[T-001]" in other_process.logs(run_id)[0]
    clock.now += 5.0
    result = worker.poll(run_id)
    assert result is not None and result.outcome is AgentOutcome.DONE
    assert result.head_sha == f"task/t-001@{run_id.split('.')[1]}"
    assert "commit and push" in result.log
    other_process.stop(run_id)  # no shared memory needed
    with pytest.raises(AgentRunNotFound):
        worker.poll("run-1")


def test_zero_step_runs_finish_at_once() -> None:
    runner = SimulatedAgentRunner(0.0, clock=Clock())
    assert runner.poll(runner.start(task(Role.TEST_WRITER))) is not None


def test_diff_depends_on_its_arguments_only() -> None:
    repo = RepoRef("r", "fake://r.git")
    one = StatelessFakeGit().diff(repo, "main", "task/t-001")
    two = StatelessFakeGit().diff(repo, "main", "task/t-001")
    assert one == two and one[0].startswith("diff --git") and one[1] is False


def test_factory_builds_the_fake_scheduler(sessions: sessionmaker[Session]) -> None:
    settings = make_settings(pack_mode="fake", run_token_secret="", fake_step_s=0.0)
    scheduler = build_scheduler(settings, sessions, None)
    assert scheduler is not None
    pid = make_ready_project(sessions)
    assert scheduler.start_project(pid)
    for _ in range(400):
        scheduler.tick()
        with sessions() as db:
            built = [m.status for m in demo.milestones_of(db, pid)]
        if built == ["built"] * 3:
            return
    raise AssertionError(built)


def test_fake_mode_refuses_production_and_speeds_up_the_loop() -> None:
    with pytest.raises(ValueError, match="production"):
        Settings(pack_mode="fake", env="production")
    assert Settings(pack_mode="fake").scheduler_interval_s == 0.5
    assert Settings(pack_mode="fake", scheduler_interval_s=3).scheduler_interval_s == 3
    assert Settings().scheduler_interval_s == 5.0


def fake_client(sessions: sessionmaker[Session], redis: FakeStreamRedis) -> TestClient:
    app = create_app(
        {"database": lambda: None, "redis": lambda: None},
        settings=Settings(pack_mode="fake"),
        session_factory=sessions,
        redis=redis,
    )
    return TestClient(app)


def test_fake_demo_page_is_served_by_the_api(sessions: sessionmaker[Session]) -> None:
    from sqlalchemy import select

    from cobble.db import Task

    from .scheduling import Harness
    from .test_scheduler_demo import build_all, operate

    redis = FakeStreamRedis()
    from cobble.capabilities.fakes_preview import FakePreviewProvider

    h = Harness(sessions, preview=FakePreviewProvider(), redis=redis)
    pid = make_ready_project(sessions)
    client = fake_client(sessions, redis)
    h.start(pid)
    assert client.get(f"/demo/{pid}/M1/").status_code == 404  # not built yet
    build_all(h, pid)
    page = client.get(f"/demo/{pid}/M1/")
    assert page.status_code == 200
    assert page.text.count('data-testid="todo"') == 5
    assert "Book the dentist appointment" in page.text
    assert page.headers["content-security-policy"].startswith("sandbox")
    assert client.get(f"/demo/{pid}/M3").text.count('data-testid="todo"') == 6
    assert client.get("/demo/not-a-uuid/M1/").status_code == 404
    operate(
        h, pid, lambda db, p: demo.add_comment(db, demo.redis_emitter(redis), p, "M1", "<b>Hi</b>")
    )
    with sessions() as db:
        task = db.scalars(select(Task).where(Task.ref == "C-001")).one()
        task.state = "merged"
        db.commit()
    again = client.get(f"/demo/{pid}/M1/")
    assert again.status_code == 404  # re-opened: pending until rebuilt
    h.scheduler.tick()
    html = client.get(f"/demo/{pid}/M1/").text
    assert "&lt;b&gt;Hi&lt;/b&gt;" in html and "<b>Hi</b>" not in html


def test_real_mode_does_not_serve_demo_pages(sessions: sessionmaker[Session]) -> None:
    app = create_app(
        {"database": lambda: None, "redis": lambda: None},
        settings=Settings(),
        session_factory=sessions,
        redis=FakeStreamRedis(),
    )
    assert TestClient(app).get(f"/demo/{uuid.uuid4()}/M1/").status_code == 404
