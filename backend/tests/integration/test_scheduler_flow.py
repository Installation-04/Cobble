"""The scheduler against real Postgres and Redis, with fakes for git, CI and the agents.

Needs COBBLE_TEST_DATABASE_URL and COBBLE_TEST_REDIS_URL. The test deletes the project stream
and the `cobble:jobs` stream it uses: do not share the Redis with a live stack.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from redis import Redis
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from cobble.api.app import create_app
from cobble.auth.sessions import create_session
from cobble.capabilities.agent import AgentOutcome
from cobble.capabilities.ci import CIState
from cobble.capabilities.fakes import FakeAgentRunner, FakeCIProvider, FakeGitProvider
from cobble.config import Settings
from cobble.db import Plan, Project, Task, TaskRun, User, make_engine, make_session_factory
from cobble.events import JOBS_STREAM, project_stream
from cobble.scheduler import Scheduler
from cobble.worker import consume_jobs_once, ensure_jobs_group, make_job_handler

pytestmark = pytest.mark.integration

H = {"X-Requested-With": "cobble"}
API = "/api/v1"
SECRET = "integration-secret"


def plan() -> dict[str, Any]:
    def task(i: int, deps: list[str]) -> dict[str, Any]:
        return {
            "id": f"T-00{i}",
            "title": f"Task {i}",
            "milestone": "M1",
            "depends_on": deps,
            "files": [f"app/f{i}.py", f"tests/t{i}.py"],
            "acceptance": ["it works"],
            "tests": f"tests/t{i}.py",
            "size": "S",
            "role": "backend",
        }

    return {
        "milestones": [{"id": "M1", "title": "All"}],
        "tasks": [task(1, []), task(2, ["T-001"]), task(3, ["T-001"]), task(4, ["T-002", "T-003"])],
    }


@pytest.fixture
def stack(
    migrated_database: str, redis_url: str
) -> Iterator[tuple[sessionmaker[Session], Redis, uuid.UUID, Settings]]:
    engine = make_engine(migrated_database)
    sessions = make_session_factory(engine)
    redis = Redis.from_url(redis_url)
    redis.delete(JOBS_STREAM)
    settings = Settings(
        database_url=migrated_database,
        redis_url=redis_url,
        run_token_secret=SECRET,
        role_models={"planner": "strong", "worker": "cheap"},
        max_parallel_agents=2,
    )
    with sessions() as db:
        user = User(email=f"{uuid.uuid4().hex[:8]}@example.com", password_hash="x")
        db.add(user)
        db.flush()
        project = Project(owner_id=user.id, name="Integration", phase="ready")
        db.add(project)
        db.flush()
        db.add(Plan(project_id=project.id, version=1, plan=plan(), estimate={}, status="approved"))
        db.commit()
        project_id = project.id
    redis.delete(project_stream(project_id))
    yield sessions, redis, project_id, settings
    with sessions() as db:
        owner = db.get(Project, project_id)
        if owner is not None:
            db.delete(db.get(User, owner.owner_id))  # cascades to the project, tasks, runs
            db.commit()
    redis.delete(project_stream(project_id), JOBS_STREAM)
    redis.close()
    engine.dispose()


def events(redis: Redis, project_id: uuid.UUID) -> list[tuple[str, dict[str, Any]]]:
    rows = redis.xrange(project_stream(project_id))
    return [(f[b"type"].decode(), json.loads(f[b"payload"])) for _id, f in rows]


def test_start_job_then_scheduler_completes_with_a_resume(
    stack: tuple[sessionmaker[Session], Redis, uuid.UUID, Settings],
) -> None:
    sessions, redis, project_id, settings = stack
    ci = FakeCIProvider(default=CIState.SUCCESS)
    git = FakeGitProvider(ci)
    agents = FakeAgentRunner(
        script={("T-002", "worker", 1): AgentOutcome.FAILED}, polls_before_done=2
    )

    def scheduler() -> Scheduler:
        return Scheduler(sessions, git, ci, agents, settings, redis=redis)

    # API -> job stream -> worker handler -> start_project.
    app = create_app(
        {"database": lambda: None, "redis": lambda: None},
        settings=settings,
        session_factory=sessions,
        redis=redis,
    )
    client = TestClient(app)
    with sessions() as db:
        project = db.get(Project, project_id)
        assert project is not None
        client.cookies.set("cobble_session", create_session(db, project.owner_id))
    assert client.post(f"{API}/projects/{project_id}/start", headers=H).status_code == 202
    ensure_jobs_group(redis)
    first = scheduler()
    handler = make_job_handler(None, first, redis)  # type: ignore[arg-type]
    assert consume_jobs_once(redis, "test", handler, block_ms=100) == 1
    assert client.get(f"{API}/projects").json()[0]["phase"] == "building"

    for _ in range(9):
        first.tick()
    with sessions() as db:
        running = db.scalars(select(TaskRun).where(TaskRun.state == "running")).all()
    assert running  # a run is in flight when the "worker" dies

    # Crash: a new Scheduler, same Postgres, same Redis, same agent service.
    del first
    second = scheduler()
    second.reconcile()
    for _ in range(200):
        second.tick()
        with sessions() as db:
            if db.get(Project, project_id).phase == "done":  # type: ignore[union-attr]
                break
    else:
        pytest.fail("the project never finished")

    with sessions() as db:
        tasks = {t.ref: t for t in db.scalars(select(Task).where(Task.project_id == project_id))}
    assert {t.state for t in tasks.values()} == {"merged"}
    assert tasks["T-002"].attempts == 2
    assert len(git.merged) == len(git.merge_calls) == 4
    markers = [t.marker for t in agents.runs]
    assert len(markers) == len(set(markers)) == 9  # 4 test-writers, 4 workers, 1 retry
    listed = client.get(f"{API}/projects/{project_id}/tasks").json()
    assert [t["state"] for t in listed] == ["merged"] * 4
    types = [t for t, _ in events(redis, project_id)]
    assert types.count("project.done") == 1
    assert types.index("project.building") < types.index("project.done")
