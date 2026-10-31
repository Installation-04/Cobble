from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from cobble.auth import runtoken
from cobble.capabilities.agent import AgentOutcome, AgentTask
from cobble.capabilities.ci import CIState
from cobble.capabilities.fakes import FakeAgentRunner, FakeCIProvider, FakeGitProvider
from cobble.capabilities.git import MergeRefused, MergeRequestRef
from cobble.db import Project, Task, TaskRun
from cobble.scheduler import StartError
from cobble.scheduler.materialize import NoApprovedPlan, materialize_tasks

from .scheduling import SECRET, Harness, make_ready_project, make_settings, script, todo_plan

DONE = AgentOutcome.DONE
FAILED = AgentOutcome.FAILED


@pytest.fixture
def pid(sessions: sessionmaker[Session]) -> uuid.UUID:
    return make_ready_project(sessions)


# --- materialize and start ------------------------------------------------------------------


def test_materialize_creates_one_task_per_plan_task_and_is_idempotent(
    sessions: sessionmaker[Session], pid: uuid.UUID
) -> None:
    with sessions() as db:
        assert materialize_tasks(db, pid) == 11
        db.commit()
        first = {t.ref: t for t in db.scalars(select(Task))}
        assert materialize_tasks(db, pid) == 0
        db.commit()
        again = {t.ref: t for t in db.scalars(select(Task))}
    assert len(again) == 11
    t3 = first["T-003"]
    assert (t3.state, t3.attempts, t3.escalated) == ("todo", 0, False)
    assert t3.depends_on == ["T-002"]
    assert t3.tests == "tests/test_todos_create_list.py"
    assert t3.files == ["app/api/todos.py", "tests/test_todos_create_list.py"]
    assert t3.size == "M"
    assert t3.role == "backend"
    assert t3.milestone == "M1"
    assert t3.acceptance


def test_materialize_never_resets_a_task_that_progressed(
    sessions: sessionmaker[Session], pid: uuid.UUID
) -> None:
    with sessions() as db:
        materialize_tasks(db, pid)
        task = db.scalars(select(Task).where(Task.ref == "T-001")).one()
        task.state = "merged"
        db.commit()
        materialize_tasks(db, pid)
        db.commit()
        assert db.scalars(select(Task).where(Task.ref == "T-001")).one().state == "merged"


def test_materialize_needs_an_approved_plan(sessions: sessionmaker[Session]) -> None:
    unapproved = make_ready_project(sessions, approved=False)
    with sessions() as db, pytest.raises(NoApprovedPlan):
        materialize_tasks(db, unapproved)


def test_start_project_creates_repo_activates_ci_and_materializes(
    sessions: sessionmaker[Session], pid: uuid.UUID
) -> None:
    h = Harness(sessions)
    h.start(pid)
    assert h.phase(pid) == "building"
    assert len(h.tasks(pid)) == 11
    with sessions() as db:
        project = db.get(Project, pid)
        assert project is not None
        assert project.repo_name is not None
        assert project.repo_name.startswith("my-todo-app-")
        assert project.repo_clone_url == f"fake://{project.repo_name}.git"
        assert h.git.repos == {project.repo_name: Path("/templates/fastapi-react")}
        assert h.ci.active == {project.repo_name}
    types = [t for t, _ in h.events(pid)]
    assert types == ["phase.changed", "project.building"]
    assert h.events(pid)[0][1] == {"phase": "building"}
    # Starting again changes nothing and publishes nothing.
    h.start(pid)
    assert len(h.git.repos) == 1
    assert len(h.events(pid)) == 2


def test_start_project_refuses_other_phases_and_missing_plans(
    sessions: sessionmaker[Session],
) -> None:
    h = Harness(sessions)
    early = make_ready_project(sessions, phase="plan_review")
    with pytest.raises(StartError) as wrong:
        h.scheduler.start_project(early)
    assert wrong.value.code == "wrong_phase"
    no_plan = make_ready_project(sessions, approved=False)
    with pytest.raises(StartError) as missing:
        h.scheduler.start_project(no_plan)
    assert missing.value.code == "no_plan"
    assert h.phase(no_plan) == "ready"
    with pytest.raises(StartError) as unknown:
        h.scheduler.start_project(uuid.uuid4())
    assert unknown.value.code == "not_found"


class BrokenGit(FakeGitProvider):
    def create_repo_from_template(self, name: str, template_dir: Path):  # type: ignore[no-untyped-def]
        raise RuntimeError("git server down")


def test_start_job_reports_failures_and_keeps_the_project_ready(
    sessions: sessionmaker[Session], pid: uuid.UUID
) -> None:
    h = Harness(sessions, git=BrokenGit())
    assert h.scheduler.run_start_job(pid) is False
    assert h.phase(pid) == "ready"
    assert h.events(pid) == [
        ("job.started", {"kind": "start"}),
        ("job.failed", {"kind": "start", "code": "repo_error"}),
    ]
    ok = Harness(sessions)
    assert ok.scheduler.run_start_job(pid) is True
    assert ok.phase(pid) == "building"


def test_repository_created_before_a_crash_is_reused(
    sessions: sessionmaker[Session], pid: uuid.UUID
) -> None:
    class FailingCI(FakeCIProvider):
        broken = True

        def activate(self, repo):  # type: ignore[no-untyped-def]
            if self.broken:
                raise RuntimeError("ci down")
            super().activate(repo)

    ci = FailingCI(default=CIState.SUCCESS)
    h = Harness(sessions, ci=ci)
    with pytest.raises(StartError) as error:
        h.scheduler.start_project(pid)
    assert error.value.code == "ci_error"
    assert h.phase(pid) == "ready"
    ci.broken = False
    h.start(pid)
    assert len(h.git.repos) == 1  # not created twice
    assert h.phase(pid) == "building"


# --- the whole backlog ----------------------------------------------------------------------


def test_reference_backlog_completes_alone(sessions: sessionmaker[Session], pid: uuid.UUID) -> None:
    agents = FakeAgentRunner(polls_before_done=1)  # runs stay in flight for a tick
    h = Harness(sessions, agents=agents)
    h.start(pid)
    h.run_until(pid)

    tasks = h.tasks(pid)
    assert {t.state for t in tasks.values()} == {"merged"}
    assert all(t.attempts == 1 and not t.escalated for t in tasks.values())
    assert h.phase(pid) == "done"

    # One merge per task, never twice, dependencies first.
    merged_branches = [m.source_branch for m in h.git.merged]
    assert sorted(merged_branches) == sorted(f"task/{ref.lower()}" for ref in tasks)
    assert len(h.git.merge_calls) == len(h.git.merged) == 11
    position = {ref: merged_branches.index(f"task/{ref.lower()}") for ref in tasks}
    for ref, task in tasks.items():
        for dep in task.depends_on:
            assert position[dep] < position[ref], (dep, ref)

    # Tests first: the test-writer is started before the worker, and finished before it starts.
    assert len(agents.runs) == 22
    for ref in tasks:
        (writer,) = h.started(ref, "test-writer")
        (worker,) = h.started(ref, "worker")
        assert writer < worker
        runs = h.runs(ref, pid)
        assert [(r.kind, r.attempt, r.state) for r in runs] == [
            ("test-writer", 1, "done"),
            ("worker", 1, "done"),
        ]
        assert runs[0].finished_at is not None
        assert runs[0].agent_run_id and runs[1].agent_run_id
        assert runs[1].head_sha == f"task/{ref.lower()}@1"
        assert runs[0].model == "cheap"

    # Runs got what the agent service needs.
    first = agents.runs[0]
    assert first.marker == "[cobble-task:T-001:test-writer:1]"
    assert first.instructions.startswith(first.marker)
    assert first.repo_clone_url.startswith("fake://my-todo-app-")
    assert first.base_branch == "main"
    assert first.branch == "task/t-001"
    assert first.files == ["app/main.py", "tests/test_health.py"]
    assert first.test_command == "uv run pytest -q tests/test_health.py"
    claims = runtoken.verify(SECRET, first.run_token)
    assert (claims.project_id, claims.role, claims.model_override) == (pid, "test-writer", None)
    assert claims.task_id == tasks["T-001"].id

    # Events: a state history per task and the project-level ones.
    events = h.events(pid)
    types = [t for t, _ in events]
    assert types[:2] == ["phase.changed", "project.building"]
    assert types[-2:] == ["phase.changed", "project.done"]
    assert events[-1][1] == {"tasks": 11}
    history = [p["state"] for t, p in events if t == "task.updated" and p["task_id"] == "T-003"]
    assert history == ["writing_tests", "implementing", "ci", "merged"]
    final = [p for t, p in events if t == "task.updated" and p["task_id"] == "T-003"][-1]
    assert final == {"task_id": "T-003", "state": "merged", "attempts": 1}


def test_independent_tasks_run_in_parallel_up_to_the_cap(
    sessions: sessionmaker[Session], pid: uuid.UUID
) -> None:
    h2 = Harness(sessions, agents=FakeAgentRunner(polls_before_done=30))
    other = make_ready_project(
        sessions,
        plan={
            "milestones": [{"id": "M1", "title": "m"}],
            "tasks": [
                {
                    "id": f"T-00{i}",
                    "title": f"t{i}",
                    "milestone": "M1",
                    "depends_on": [],
                    "files": [f"app/f{i}.py", f"tests/t{i}.py"],
                    "acceptance": ["ok"],
                    "tests": f"tests/t{i}.py",
                    "size": "S",
                    "role": "backend",
                }
                for i in range(1, 5)
            ],
        },
    )
    h2.start(other)
    h2.scheduler.tick()
    assert len(h2.agents.runs) == 2  # cap
    h2.scheduler.tick()
    assert len(h2.agents.runs) == 2
    assert sorted(h2.states(other).values()) == ["todo", "todo", "writing_tests", "writing_tests"]


def test_tasks_sharing_a_file_never_run_together(sessions: sessionmaker[Session]) -> None:
    def task(i: int, files: list[str]) -> dict[str, object]:
        return {
            "id": f"T-00{i}",
            "title": f"t{i}",
            "milestone": "M1",
            "depends_on": [],
            "files": files,
            "acceptance": ["ok"],
            "tests": f"tests/t{i}.py",
            "size": "S",
            "role": "backend",
        }

    plan = {
        "milestones": [{"id": "M1", "title": "m"}],
        "tasks": [
            task(1, ["app/shared.py", "tests/t1.py"]),
            task(2, ["app/shared.py", "tests/t2.py"]),
            task(3, ["app/other.py", "tests/t3.py"]),
        ],
    }
    project = make_ready_project(sessions, plan=plan)
    h = Harness(sessions, agents=FakeAgentRunner(polls_before_done=2))
    h.start(project)
    h.scheduler.tick()
    assert h.states(project) == {
        "T-001": "writing_tests",
        "T-002": "todo",
        "T-003": "writing_tests",
    }
    h.run_until(project)  # invariants (no shared file among active tasks) checked every tick
    assert {t.state for t in h.tasks(project).values()} == {"merged"}


# --- CI red, retries, escalation, failure -----------------------------------------------------


def test_red_ci_starts_another_attempt_with_the_ci_log(
    sessions: sessionmaker[Session], pid: uuid.UUID
) -> None:
    h = Harness(sessions)
    h.start(pid)
    repo = h.repo_ref(pid)
    h.ci.set_result(repo, "task/t-001@1", CIState.FAILURE, "FAILED tests/test_health.py::test_ok")
    h.run_until(pid)

    t1 = h.tasks(pid)["T-001"]
    assert (t1.state, t1.attempts, t1.escalated) == ("merged", 2, False)
    runs = h.runs("T-001", pid)
    assert [(r.kind, r.attempt, r.state) for r in runs] == [
        ("test-writer", 1, "done"),
        ("worker", 1, "rejected"),
        ("worker", 2, "done"),
    ]
    worker_runs = [t for t in h.agents.runs if t.role.value == "worker" and "T-001" in t.marker]
    assert "previous attempt" not in worker_runs[0].instructions
    assert worker_runs[1].instructions.startswith("[cobble-task:T-001:worker:2]")
    assert "FAILED tests/test_health.py::test_ok" in worker_runs[1].instructions
    assert len(h.git.merged) == 11  # the red attempt merged nothing
    assert [m.source_branch for m in h.git.merged].count("task/t-001") == 1
    # Same branch and one merge request for the whole task.
    assert len({t.branch for t in worker_runs}) == 1
    assert len({k for k in h.git.opened if k[1] == "task/t-001"}) == 1


class RefusingGit(FakeGitProvider):
    """Refuses the first merge of a branch even though CI is green."""

    def __init__(self, ci: FakeCIProvider, branch: str) -> None:
        super().__init__(ci)
        self.branch = branch
        self.refused = 0

    def merge(self, request: MergeRequestRef) -> None:
        if request.source_branch == self.branch and self.refused == 0:
            self.refused += 1
            raise MergeRefused("branch is out of date")
        super().merge(request)


def test_refused_merge_is_a_ci_problem(sessions: sessionmaker[Session], pid: uuid.UUID) -> None:
    ci = FakeCIProvider(default=CIState.SUCCESS)
    git = RefusingGit(ci, "task/t-002")
    h = Harness(sessions, ci=ci, git=git)
    h.start(pid)
    h.run_until(pid)
    assert git.refused == 1
    t2 = h.tasks(pid)["T-002"]
    assert (t2.state, t2.attempts) == ("merged", 2)
    retry = next(t for t in h.agents.runs if t.marker == "[cobble-task:T-002:worker:2]")
    assert "merge refused: branch is out of date" in retry.instructions


class FlakyGit(FakeGitProvider):
    def __init__(self, ci: FakeCIProvider) -> None:
        super().__init__(ci)
        self.failures = 2

    def merge(self, request: MergeRequestRef) -> None:
        if self.failures:
            self.failures -= 1
            raise ConnectionError("git server unreachable")
        super().merge(request)


def test_provider_outage_is_retried_not_counted(
    sessions: sessionmaker[Session], pid: uuid.UUID
) -> None:
    ci = FakeCIProvider(default=CIState.SUCCESS)
    h = Harness(sessions, ci=ci, git=FlakyGit(ci))
    h.start(pid)
    h.run_until(pid)
    assert {t.attempts for t in h.tasks(pid).values()} == {1}


def test_escalation_after_n_failed_attempts_uses_the_escalation_model(
    sessions: sessionmaker[Session], pid: uuid.UUID
) -> None:
    agents = FakeAgentRunner(
        script=script(
            ("T-001", "worker", 1, FAILED),
            ("T-001", "worker", 2, AgentOutcome.TIMEOUT),
        )
    )
    h = Harness(sessions, agents=agents)  # escalate_after=2 (default), planner model = "strong"
    h.start(pid)
    h.run_until(pid)

    t1 = h.tasks(pid)["T-001"]
    assert (t1.state, t1.attempts, t1.escalated) == ("merged", 3, True)
    workers = [t for t in agents.runs if "T-001:worker" in t.marker]
    assert [t.marker for t in workers] == [f"[cobble-task:T-001:worker:{i}]" for i in (1, 2, 3)]
    overrides = [runtoken.verify(SECRET, t.run_token).model_override for t in workers]
    assert overrides == [None, None, "strong"]
    assert [t.model for t in workers] == ["cheap", "cheap", "strong"]
    runs = h.runs("T-001", pid)
    assert [(r.attempt, r.state, r.model) for r in runs if r.kind == "worker"] == [
        (1, "failed", "cheap"),
        (2, "timeout", "cheap"),
        (3, "done", "strong"),
    ]
    # Other tasks are never escalated; the failure log feeds the next attempt.
    assert not any(t.escalated for ref, t in h.tasks(pid).items() if ref != "T-001")
    assert "agent timeout" in workers[2].instructions
    # The test-writer is not part of the worker's attempt count.
    assert len([t for t in agents.runs if "T-001:test-writer" in t.marker]) == 1


def test_explicit_escalation_model_and_threshold(
    sessions: sessionmaker[Session], pid: uuid.UUID
) -> None:
    agents = FakeAgentRunner(script=script(("T-001", "worker", 1, FAILED)))
    settings = make_settings(escalate_after=1, escalation_model="frontier")
    h = Harness(sessions, agents=agents, settings=settings)
    h.start(pid)
    h.run_until(pid)
    workers = [t for t in agents.runs if "T-001:worker" in t.marker]
    assert [runtoken.verify(SECRET, t.run_token).model_override for t in workers] == [
        None,
        "frontier",
    ]


def test_task_fails_after_max_attempts_and_blocks_its_dependents(
    sessions: sessionmaker[Session], pid: uuid.UUID
) -> None:
    agents = FakeAgentRunner(script=script(*[("T-002", "worker", n, FAILED) for n in range(1, 10)]))
    h = Harness(sessions, agents=agents)
    h.start(pid)
    h.tick_until_settled(pid)

    states = h.states(pid)
    assert states["T-002"] == "failed"
    assert states["T-001"] == "merged" and states["T-005"] == "merged"
    blocked = {"T-003", "T-004", "T-006", "T-007", "T-008", "T-009", "T-010", "T-011"}
    assert {ref for ref, s in states.items() if s == "blocked"} == blocked
    t2 = h.tasks(pid)["T-002"]
    assert t2.attempts == 4 and t2.escalated
    assert t2.last_error is not None and "agent failed" in t2.last_error
    assert len([t for t in agents.runs if "T-002:worker" in t.marker]) == 4  # max_attempts
    assert not any("T-003" in t.marker for t in agents.runs)  # blocked tasks never start
    assert h.phase(pid) == "building"  # not done: there is nothing left that can run
    blocked_events = [
        p for t, p in h.events(pid) if t == "task.updated" and p["state"] == "blocked"
    ]
    assert {p["task_id"] for p in blocked_events} == blocked
    assert "project.done" not in [t for t, _ in h.events(pid)]


def test_loop_detected_run_is_a_failed_attempt(
    sessions: sessionmaker[Session], pid: uuid.UUID
) -> None:
    agents = FakeAgentRunner(script=script(("T-001", "worker", 1, AgentOutcome.LOOP_DETECTED)))
    h = Harness(sessions, agents=agents)
    h.start(pid)
    h.run_until(pid)
    runs = [r for r in h.runs("T-001", pid) if r.kind == "worker"]
    assert [(r.attempt, r.state) for r in runs] == [(1, "loop_detected"), (2, "done")]
    retry = next(t for t in agents.runs if t.marker.endswith("T-001:worker:2]"))
    assert "agent loop_detected" in retry.instructions
    assert h.tasks(pid)["T-001"].attempts == 2


def test_test_writer_failure_retries_then_fails_the_task(sessions: sessionmaker[Session]) -> None:
    plan = {
        "milestones": [{"id": "M1", "title": "m"}],
        "tasks": [
            {
                "id": "T-001",
                "title": "t",
                "milestone": "M1",
                "depends_on": [],
                "files": ["app/a.py", "tests/a.py"],
                "acceptance": ["ok"],
                "tests": "tests/a.py",
                "size": "S",
                "role": "backend",
            }
        ],
    }
    project = make_ready_project(sessions, plan=plan)
    agents = FakeAgentRunner(script=script(("T-001", "test-writer", 1, FAILED)))
    h = Harness(sessions, agents=agents, settings=make_settings(max_attempts=3))
    h.start(project)
    h.tick_until_settled(project)
    assert h.states(project) == {"T-001": "failed"}
    assert len(agents.runs) == 3  # three test-writer tries, no worker ever started
    assert not h.started("T-001", "worker")


def test_ci_that_never_finishes_counts_as_a_failed_attempt(
    sessions: sessionmaker[Session], pid: uuid.UUID
) -> None:
    ci = FakeCIProvider(default=CIState.PENDING)
    clock_h = Harness(sessions, ci=ci, settings=make_settings(ci_timeout_s=600))
    clock_h.start(pid)
    for _ in range(4):
        clock_h.scheduler.tick()
    assert clock_h.states(pid)["T-001"] == "ci"
    clock_h.clock.advance(601)
    clock_h.scheduler.tick()
    runs = [r for r in clock_h.runs("T-001", pid) if r.kind == "worker"]
    assert [(r.attempt, r.state) for r in runs][:2] == [(1, "rejected"), (2, "running")]
    retry = next(t for t in clock_h.agents.runs if t.marker.endswith("T-001:worker:2]"))
    assert "CI did not finish in time" in retry.instructions


# --- budget pause ------------------------------------------------------------------------------


def test_paused_project_starts_nothing_but_running_work_finishes(
    sessions: sessionmaker[Session], pid: uuid.UUID
) -> None:
    agents = FakeAgentRunner(polls_before_done=2)
    h = Harness(sessions, agents=agents)
    h.start(pid)
    h.scheduler.tick()
    assert len(agents.runs) == 1  # T-001's test-writer is in flight
    h.set_status(pid, "paused")  # the budget was reached

    for _ in range(10):
        h.scheduler.tick()
    # The in-flight run finished, but no worker (or anything else) was started after it.
    assert len(agents.runs) == 1
    assert h.states(pid)["T-001"] == "paused"
    assert [r.state for r in h.runs("T-001", pid)] == ["done"]

    h.set_status(pid, "active")  # the user raised the budget
    h.run_until(pid)
    assert h.states(pid)["T-001"] == "merged"
    assert [(r.kind, r.attempt) for r in h.runs("T-001", pid)] == [
        ("test-writer", 1),
        ("worker", 1),
    ]
    assert len(h.started("T-001", "test-writer")) == 1  # the finished test-writer is not redone


def test_a_paused_project_still_merges_a_green_merge_request(
    sessions: sessionmaker[Session], pid: uuid.UUID
) -> None:
    ci = FakeCIProvider(default=CIState.PENDING)
    h = Harness(sessions, ci=ci)
    h.start(pid)
    for _ in range(4):
        h.scheduler.tick()
    assert h.states(pid)["T-001"] == "ci"
    h.set_status(pid, "paused")
    ci.default = CIState.SUCCESS
    h.scheduler.tick()
    assert h.states(pid)["T-001"] == "merged"
    h.scheduler.tick()
    assert len(h.agents.runs) == 2  # no new run was started (T-002, T-005 stay todo)
    assert h.states(pid)["T-002"] == "todo"


def test_budget_outcome_parks_the_task_without_using_an_attempt(
    sessions: sessionmaker[Session], pid: uuid.UUID
) -> None:
    agents = FakeAgentRunner(script=script(("T-001", "worker", 1, AgentOutcome.BUDGET)))
    h = Harness(sessions, agents=agents)
    h.start(pid)
    for _ in range(20):
        h.scheduler.tick()
        if any(r.state == "budget" for r in h.runs("T-001", pid)):
            break
    agents.script.clear()  # the budget was raised: the same attempt runs again normally
    h.run_until(pid)
    t1 = h.tasks(pid)["T-001"]
    assert t1.state == "merged"
    assert t1.attempts == 1  # the budget stop did not count
    worker_runs = [r for r in h.runs("T-001", pid) if r.kind == "worker"]
    assert {r.attempt for r in worker_runs} == {1}
    assert worker_runs[0].state == "budget"
    assert worker_runs[-1].state == "done"


# --- agent service trouble ---------------------------------------------------------------------


def test_unreachable_agent_service_is_retried_without_using_attempts(
    sessions: sessionmaker[Session], pid: uuid.UUID
) -> None:
    agents = FakeAgentRunner()
    agents.unavailable = True
    h = Harness(sessions, agents=agents)
    h.start(pid)
    for _ in range(3):
        h.scheduler.tick()
    assert h.states(pid)["T-001"] == "todo"
    assert h.runs("T-001", pid) == []  # no half-started run left behind
    agents.unavailable = False
    h.run_until(pid)
    assert {t.attempts for t in h.tasks(pid).values()} == {1}


def test_agent_service_going_down_mid_run_keeps_the_run(
    sessions: sessionmaker[Session], pid: uuid.UUID
) -> None:
    agents = FakeAgentRunner(polls_before_done=1)
    h = Harness(sessions, agents=agents)
    h.start(pid)
    h.scheduler.tick()
    agents.unavailable = True
    for _ in range(3):
        h.scheduler.tick()
    assert [r.state for r in h.runs("T-001", pid)] == ["running"]
    agents.unavailable = False
    h.run_until(pid)
    assert [r.state for r in h.runs("T-001", pid)] == ["done", "done"]


def test_run_unknown_to_the_service_is_a_failed_attempt(
    sessions: sessionmaker[Session], pid: uuid.UUID
) -> None:
    agents = FakeAgentRunner(polls_before_done=1)
    h = Harness(sessions, agents=agents)
    h.start(pid)
    h.scheduler.tick()
    (run,) = h.runs("T-001", pid)
    assert run.agent_run_id is not None
    agents.lost.add(run.agent_run_id)
    h.scheduler.tick()
    first = h.runs("T-001", pid)[0]
    assert first.state == "failed"
    assert first.log_tail is not None and "no longer knows" in first.log_tail
    h.run_until(pid)
    assert h.states(pid)["T-001"] == "merged"
    assert len(h.started("T-001", "test-writer")) == 2  # the lost test-writer was retried


class RejectingAgents(FakeAgentRunner):
    def start(self, task: AgentTask) -> str:
        from cobble.capabilities.agent import AgentRejected

        raise AgentRejected("bad request")


def test_refused_run_counts_as_a_failed_attempt(
    sessions: sessionmaker[Session], pid: uuid.UUID
) -> None:
    h = Harness(sessions, agents=RejectingAgents(), settings=make_settings(max_attempts=2))
    h.start(pid)
    h.tick_until_settled(pid)
    assert h.states(pid)["T-001"] == "failed"
    assert [r.state for r in h.runs("T-001", pid)] == ["failed", "failed"]


# --- kill and resume ----------------------------------------------------------------------------


def test_kill_and_resume_completes_without_duplicates(
    sessions: sessionmaker[Session], pid: uuid.UUID
) -> None:
    """The scheduler dies with runs in flight; a new one on the same database finishes the job."""
    agents = FakeAgentRunner(polls_before_done=3)  # the agent service outlives the worker
    first = Harness(sessions, agents=agents)
    first.start(pid)
    for _ in range(7):
        first.scheduler.tick()
    inflight_before = [
        r for ref in first.states(pid) for r in first.runs(ref, pid) if r.state == "running"
    ]
    assert inflight_before, "the test needs a run in flight when the worker dies"
    started_before = len(agents.runs)

    # Simulated crash: the Scheduler object is discarded, nothing is cleaned up.
    resumed = Harness(
        sessions, agents=agents, ci=first.ci, git=first.git, redis=first.redis, clock=first.clock
    )
    del first
    report = resumed.scheduler.reconcile()
    assert report.lost == 0
    assert report.reattached == len(inflight_before)
    # Reconcile started nothing: every task that had an active run still has exactly that one.
    assert len(agents.runs) == started_before
    resumed.run_until(pid)

    assert {t.state for t in resumed.tasks(pid).values()} == {"merged"}
    assert len(agents.runs) == 22  # 11 test-writers + 11 workers, none repeated
    markers = [t.marker for t in agents.runs]
    assert len(markers) == len(set(markers))
    assert len(resumed.git.merged) == len(resumed.git.merge_calls) == 11
    for ref in resumed.tasks(pid):
        assert [(r.kind, r.attempt) for r in resumed.runs(ref, pid)] == [
            ("test-writer", 1),
            ("worker", 1),
        ]
    assert [t for t, _ in resumed.events(pid)].count("project.done") == 1


def test_crash_after_the_merge_but_before_it_was_recorded_merges_once(
    sessions: sessionmaker[Session], pid: uuid.UUID
) -> None:
    ci = FakeCIProvider(default=CIState.PENDING)
    h = Harness(sessions, ci=ci)
    h.start(pid)
    for _ in range(4):
        h.scheduler.tick()
    task = h.tasks(pid)["T-001"]
    assert task.state == "ci" and task.pr_number is not None
    # The merge went through at the git server, then the worker died before saving "merged".
    ci.default = CIState.SUCCESS
    repo = h.repo_ref(pid)
    request = MergeRequestRef(repo, task.pr_number, "task/t-001", "main", "task/t-001@1")
    h.git.merge(request)
    resumed = Harness(sessions, agents=h.agents, ci=ci, git=h.git, redis=h.redis, clock=h.clock)
    resumed.scheduler.reconcile()
    assert resumed.tasks(pid)["T-001"].state == "merged"
    assert [m.source_branch for m in h.git.merged].count("task/t-001") == 1


def test_resume_after_crash_between_run_row_and_service_call(
    sessions: sessionmaker[Session], pid: uuid.UUID
) -> None:
    h = Harness(sessions)
    h.start(pid)
    task = h.tasks(pid)["T-001"]
    with sessions() as db:  # what the database holds if the process died inside `start`
        db.add(
            TaskRun(task_id=task.id, kind="test-writer", attempt=1, model="cheap", state="pending")
        )
        db.commit()
    report = h.new_scheduler().reconcile()
    assert report.lost == 1
    h.run_until(pid)
    runs = h.runs("T-001", pid)
    assert [(r.kind, r.state) for r in runs] == [
        ("test-writer", "lost"),
        ("test-writer", "done"),
        ("worker", "done"),
    ]
    assert h.tasks(pid)["T-001"].attempts == 1  # the lost run used no attempt


def test_a_task_with_an_active_run_never_gets_a_second_one(
    sessions: sessionmaker[Session], pid: uuid.UUID
) -> None:
    agents = FakeAgentRunner(polls_before_done=50)
    h = Harness(sessions, agents=agents)
    h.start(pid)
    h.scheduler.tick()
    other = h.new_scheduler()
    for _ in range(5):
        other.tick()
        h.scheduler.tick()
    assert len([t for t in agents.runs if "T-001" in t.marker]) == 1
    task = h.tasks(pid)["T-001"]
    with sessions() as db:
        project = db.get(Project, pid)
        assert project is not None
        h.scheduler._launch(db, project, db.get(Task, task.id), "worker")  # type: ignore[arg-type]
    assert len([t for t in agents.runs if "T-001" in t.marker]) == 1


def test_only_building_projects_are_scheduled(
    sessions: sessionmaker[Session], pid: uuid.UUID
) -> None:
    h = Harness(sessions)
    h.scheduler.tick()
    assert h.agents.runs == []
    with sessions() as db:
        assert db.scalars(select(Task)).first() is None
    assert todo_plan()["tasks"]


def test_run_forever_reconciles_then_ticks_until_stopped(
    sessions: sessionmaker[Session], pid: uuid.UUID
) -> None:
    import threading

    h = Harness(sessions)
    h.start(pid)
    stop = threading.Event()
    thread = threading.Thread(target=h.scheduler.run_forever, args=(stop, 0.01))
    thread.start()
    try:
        # Poll the in-memory event stream, not the database: the test database is a single
        # shared SQLite connection that must not be used from two threads at once.
        for _ in range(500):
            if any(name == "project.done" for name, _ in h.events(pid)):
                break
            stop.wait(0.02)
    finally:
        stop.set()
        thread.join(timeout=5)
    assert not thread.is_alive()
    assert h.phase(pid) == "done"
