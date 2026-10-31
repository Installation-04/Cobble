"""Helpers shared by the scheduler tests: a project with the reference plan and a harness."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from cobble.capabilities.agent import AgentOutcome
from cobble.capabilities.ci import CIState
from cobble.capabilities.fakes import FakeAgentRunner, FakeCIProvider, FakeGitProvider
from cobble.capabilities.git import RepoRef
from cobble.config import Settings
from cobble.db import Plan, Project, Task, TaskRun, User
from cobble.events import project_stream
from cobble.scheduler import Scheduler, rules

from .fakes import FakeStreamRedis
from .planning import load_script

SECRET = "test-run-token-secret"
ROLE_MODELS = {"planner": "strong", "worker": "cheap", "test-writer": "cheap"}


def todo_plan() -> dict[str, Any]:
    """The valid plan of the to-do reference project (11 tasks, 3 milestones)."""
    plan: dict[str, Any] = load_script().valid_plan("en")
    return plan


def make_settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "run_token_secret": SECRET,
        "role_models": ROLE_MODELS,
        "default_model": "fake",
        "max_parallel_agents": 2,
        "template_dir": "/templates/fastapi-react",
    }
    values.update(overrides)
    return Settings(**values)


def make_ready_project(
    sessions: sessionmaker[Session],
    *,
    plan: dict[str, Any] | None = None,
    phase: str = "ready",
    approved: bool = True,
) -> uuid.UUID:
    with sessions() as db:
        user = User(email=f"{uuid.uuid4().hex[:8]}@example.com", password_hash="x")
        db.add(user)
        db.flush()
        project = Project(owner_id=user.id, name="My Todo App", phase=phase)
        db.add(project)
        db.flush()
        db.add(
            Plan(
                project_id=project.id,
                version=1,
                plan=plan if plan is not None else todo_plan(),
                estimate={},
                status="approved" if approved else "draft",
            )
        )
        db.commit()
        return project.id


class Clock:
    """A manual clock for the scheduler."""

    def __init__(self) -> None:
        self.now = datetime(2026, 1, 1, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


class Harness:
    """A scheduler wired to the fakes, on a shared database and a shared fake Redis."""

    def __init__(
        self,
        sessions: sessionmaker[Session],
        *,
        agents: FakeAgentRunner | None = None,
        ci: FakeCIProvider | None = None,
        git: FakeGitProvider | None = None,
        redis: FakeStreamRedis | None = None,
        settings: Settings | None = None,
        clock: Clock | None = None,
    ) -> None:
        self.sessions = sessions
        self.settings = settings or make_settings()
        self.ci = ci or FakeCIProvider(default=CIState.SUCCESS)
        self.git = git or FakeGitProvider(self.ci)
        self.agents = agents or FakeAgentRunner()
        self.redis = redis or FakeStreamRedis()
        self.clock = clock or Clock()
        self.scheduler = self.new_scheduler()

    def new_scheduler(self) -> Scheduler:
        return Scheduler(
            self.sessions,
            self.git,
            self.ci,
            self.agents,
            self.settings,
            redis=self.redis,  # type: ignore[arg-type]
            clock=self.clock,
        )

    # --- driving ---------------------------------------------------------------------------

    def start(self, project_id: uuid.UUID) -> None:
        assert self.scheduler.start_project(project_id)

    def repo_ref(self, project_id: uuid.UUID) -> RepoRef:
        with self.sessions() as db:
            project = db.get(Project, project_id)
            assert project is not None
            assert project.repo_name is not None
            assert project.repo_clone_url is not None
            return RepoRef(project.repo_name, project.repo_clone_url)

    def tasks(self, project_id: uuid.UUID) -> dict[str, Task]:
        with self.sessions() as db:
            rows = db.scalars(select(Task).where(Task.project_id == project_id))
            return {t.ref: t for t in rows}

    def states(self, project_id: uuid.UUID) -> dict[str, str]:
        return {ref: t.state for ref, t in self.tasks(project_id).items()}

    def runs(self, ref: str, project_id: uuid.UUID) -> list[TaskRun]:
        task = self.tasks(project_id)[ref]
        with self.sessions() as db:
            return list(
                db.scalars(
                    select(TaskRun).where(TaskRun.task_id == task.id).order_by(TaskRun.started_at)
                )
            )

    def phase(self, project_id: uuid.UUID) -> str:
        with self.sessions() as db:
            project = db.get(Project, project_id)
            assert project is not None
            return project.phase

    def set_status(self, project_id: uuid.UUID, status: str) -> None:
        with self.sessions() as db:
            project = db.get(Project, project_id)
            assert project is not None
            project.status = status
            db.commit()

    def check_invariants(self, project_id: uuid.UUID) -> None:
        """What must hold after every tick: the parallel cap and no shared files."""
        tasks = self.tasks(project_id).values()
        running = [t for t in tasks if t.state in rules.RUNNING]
        assert len(running) <= self.settings.max_parallel_agents
        active = [t for t in tasks if t.state in rules.ACTIVE]
        for index, first in enumerate(active):
            for second in active[index + 1 :]:
                assert not rules.overlap(first.files, second.files), (first.ref, second.ref)

    def run_until(self, project_id: uuid.UUID, *, phase: str = "done", max_ticks: int = 200) -> int:
        for tick in range(1, max_ticks + 1):
            self.scheduler.tick()
            self.check_invariants(project_id)
            if self.phase(project_id) == phase:
                return tick
        raise AssertionError(f"not {phase} after {max_ticks} ticks: {self.states(project_id)}")

    def tick_until_settled(self, project_id: uuid.UUID, max_ticks: int = 200) -> None:
        """Tick until no task is active any more (all merged, failed, blocked or waiting)."""
        for _ in range(max_ticks):
            self.scheduler.tick()
            self.check_invariants(project_id)
            if not any(s in rules.ACTIVE for s in self.states(project_id).values()):
                self.scheduler.tick()
                if not any(s in rules.ACTIVE for s in self.states(project_id).values()):
                    return
        raise AssertionError(f"still busy: {self.states(project_id)}")

    # --- observing ---------------------------------------------------------------------------

    def events(self, project_id: uuid.UUID) -> list[tuple[str, dict[str, Any]]]:
        return [
            (e["type"], json.loads(e["payload"]))
            for e in self.redis.entries(project_stream(project_id))
        ]

    def started(self, ref: str, role: str) -> list[int]:
        """Indexes (in start order) of the agent runs of a task and role."""
        return [
            index
            for index, task in enumerate(self.agents.runs)
            if task.marker.startswith(f"[cobble-task:{ref}:{role}:")
        ]


def script(
    *entries: tuple[str, str, int, AgentOutcome],
) -> dict[tuple[str, str, int], AgentOutcome]:
    return {(ref, role, attempt): outcome for ref, role, attempt, outcome in entries}
