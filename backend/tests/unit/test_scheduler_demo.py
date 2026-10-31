"""Milestones, demo tasks, comments and reverts with the scheduler on fakes (ADR 0007)."""

from __future__ import annotations

import uuid
from collections.abc import Callable

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from cobble.capabilities.agent import AgentOutcome
from cobble.capabilities.fakes_preview import FakePreviewProvider
from cobble.db import Milestone, Project, Task
from cobble.scheduler import demo
from cobble.scheduler.demo import DemoError, redis_emitter

from .scheduling import Harness, make_ready_project


@pytest.fixture
def pid(sessions: sessionmaker[Session]) -> uuid.UUID:
    return make_ready_project(sessions)


@pytest.fixture
def h(sessions: sessionmaker[Session]) -> Harness:
    return Harness(sessions, preview=FakePreviewProvider())


def milestones(h: Harness, pid: uuid.UUID) -> dict[str, Milestone]:
    with h.sessions() as db:
        return {m.ref: m for m in demo.milestones_of(db, pid)}


def tick_until(h: Harness, pid: uuid.UUID, cond: Callable[[], bool], max_ticks: int = 300) -> None:
    for _ in range(max_ticks):
        h.scheduler.tick()
        h.check_invariants(pid)
        if cond():
            return
    raise AssertionError(f"condition not reached: {h.states(pid)} {milestones(h, pid)}")


def operate(h: Harness, pid: uuid.UUID, fn: Callable[[Session, Project], object]) -> object:
    with h.sessions() as db:
        project = db.get(Project, pid)
        assert project is not None
        return fn(db, project)


def emitter(h: Harness) -> demo.Emitter:
    return redis_emitter(h.redis)


def validate(h: Harness, pid: uuid.UUID, ref: str) -> None:
    operate(h, pid, lambda db, p: demo.validate_milestone(db, emitter(h), p, ref))


def build_all(h: Harness, pid: uuid.UUID) -> None:
    """Start, then validate each milestone as soon as it is built, until the project is done."""
    h.start(pid)
    for _ in range(300):
        h.scheduler.tick()
        for ref, m in milestones(h, pid).items():
            if m.status == "built":
                validate(h, pid, ref)
        if h.phase(pid) == "done":
            return
    raise AssertionError(f"not done: {h.states(pid)} {milestones(h, pid)}")


# --- materialization ----------------------------------------------------------------------------


def test_start_creates_milestones_and_one_demo_task_per_milestone(
    h: Harness, pid: uuid.UUID
) -> None:
    h.start(pid)
    tasks = h.tasks(pid)
    assert len(tasks) == 11 + 3
    d1 = tasks["DEMO-M1"]
    plan_m1 = sorted(t.ref for t in tasks.values() if t.milestone == "M1" and t.kind == "plan")
    assert sorted(d1.depends_on) == plan_m1
    assert (d1.kind, d1.files, d1.tests, d1.role) == ("demo", ["app/seed.py"], "n/a", "worker")
    assert any("realistic" in item for item in d1.acceptance)
    ms = milestones(h, pid)
    assert sorted(ms) == ["M1", "M2", "M3"]
    assert {m.status for m in ms.values()} == {"pending"}
    assert ("My Todo App".lower().replace(" ", "-"), demo.TEMPLATE_TAG, "main") == (
        h.git.tags[0][0].rsplit("-", 1)[0],
        h.git.tags[0][1],
        h.git.tags[0][2],
    )


def test_demo_task_skips_the_test_writer(h: Harness, pid: uuid.UUID) -> None:
    h.start(pid)
    tick_until(h, pid, lambda: h.states(pid)["DEMO-M1"] == "merged")
    runs = h.runs("DEMO-M1", pid)
    assert [r.kind for r in runs] == ["worker"]
    assert h.started("DEMO-M1", "test-writer") == []
    (index,) = h.started("DEMO-M1", "worker")
    text = h.agents.runs[index].instructions
    assert "app/seed.py" in text and "realistic" in text and "idempotent" in text
    assert h.agents.runs[index].test_command == "uv run pytest -q"


def test_a_demo_task_never_runs_before_its_milestone_is_merged(h: Harness, pid: uuid.UUID) -> None:
    h.start(pid)
    for _ in range(300):
        h.scheduler.tick()
        states = h.states(pid)
        if states["DEMO-M1"] != "todo":
            assert all(
                t.state == "merged"
                for t in h.tasks(pid).values()
                if t.milestone == "M1" and t.ref != "DEMO-M1"
            )
            return
    raise AssertionError("DEMO-M1 never started")


# --- milestone lifecycle ------------------------------------------------------------------------


def test_milestone_is_built_tagged_and_deployed_once_its_tasks_are_merged(
    h: Harness, pid: uuid.UUID
) -> None:
    h.start(pid)
    tick_until(h, pid, lambda: milestones(h, pid)["M1"].status == "built")
    m1 = milestones(h, pid)["M1"]
    assert m1.tag == "milestone-M1"
    assert m1.preview_path == f"/demo/{pid}/M1/"
    assert m1.built_at is not None and m1.validated_at is None
    assert any(t[1] == "milestone-M1" and t[2] == "main" for t in h.git.tags)
    (request,) = [r for r in h.preview.deployed if r.milestone == "M1"]
    assert (request.project_id, request.ref) == (pid, "milestone-M1")
    assert request.repo_clone_url.startswith("fake://")
    events = [(t, p) for t, p in h.events(pid) if t == "milestone.updated"]
    assert (
        "milestone.updated",
        {"ref": "M1", "status": "built", "preview_state": "building"},
    ) in events
    # M2 is not built before its own tasks are merged.
    assert milestones(h, pid)["M3"].status == "pending"


def test_project_is_done_only_when_every_milestone_is_validated(h: Harness, pid: uuid.UUID) -> None:
    h.start(pid)
    tick_until(h, pid, lambda: all(m.status == "built" for m in milestones(h, pid).values()))
    assert all(s == "merged" for s in h.states(pid).values())
    for _ in range(3):
        h.scheduler.tick()
    assert h.phase(pid) == "building"
    validate(h, pid, "M1")
    validate(h, pid, "M2")
    assert h.phase(pid) == "building"
    validate(h, pid, "M3")
    assert h.phase(pid) == "done"
    types = [t for t, _ in h.events(pid)]
    assert types.count("project.done") == 1
    assert (
        "milestone.updated",
        {"ref": "M3", "status": "validated", "preview_state": "running"},
    ) in h.events(pid)


def test_preview_state_follows_the_service(sessions: sessionmaker[Session], pid: uuid.UUID) -> None:
    h = Harness(sessions, preview=FakePreviewProvider(polls_before_running=2))
    h.start(pid)
    tick_until(h, pid, lambda: milestones(h, pid)["M1"].status == "built")
    assert milestones(h, pid)["M1"].preview_state == "building"
    tick_until(h, pid, lambda: milestones(h, pid)["M1"].preview_state == "running")
    states = [
        p["preview_state"]
        for t, p in h.events(pid)
        if t == "milestone.updated" and p["ref"] == "M1"
    ]
    assert states == ["building", "running"]


def test_failed_preview_is_reported(sessions: sessionmaker[Session], pid: uuid.UUID) -> None:
    h = Harness(sessions, preview=FakePreviewProvider(fail=True))
    h.start(pid)
    tick_until(h, pid, lambda: milestones(h, pid)["M1"].preview_state == "failed")
    assert milestones(h, pid)["M1"].status == "built"


def test_deploy_is_retried_when_the_preview_service_is_down(h: Harness, pid: uuid.UUID) -> None:
    h.preview.unavailable = True
    h.start(pid)
    tick_until(h, pid, lambda: h.states(pid)["DEMO-M1"] == "merged")
    for _ in range(3):
        h.scheduler.tick()
    m1 = milestones(h, pid)["M1"]
    assert (m1.status, m1.tag) == ("pending", "milestone-M1")  # tagged, not deployed
    h.preview.unavailable = False
    # A restarted scheduler picks up from the database alone.
    h.scheduler = h.new_scheduler()
    h.scheduler.reconcile()
    m1 = milestones(h, pid)["M1"]
    assert m1.status == "built"
    assert [t for t in h.git.tags if t[1] == "milestone-M1"] == [
        (h.repo_ref(pid).name, "milestone-M1", "main")
    ]


def test_a_crash_between_merge_and_tag_is_resumed(h: Harness, pid: uuid.UUID) -> None:
    h.start(pid)
    tick_until(h, pid, lambda: h.states(pid)["DEMO-M1"] == "merged")
    # Whatever happened to the process, a new scheduler finishes the milestone.
    h.scheduler = h.new_scheduler()
    h.scheduler.reconcile()
    assert milestones(h, pid)["M1"].status == "built"


# --- validate / comment / revert ------------------------------------------------------------------


def test_validate_requires_a_built_milestone(h: Harness, pid: uuid.UUID) -> None:
    h.start(pid)
    with pytest.raises(DemoError) as err:
        validate(h, pid, "M1")
    assert (err.value.status, err.value.code) == (409, "wrong_state")
    with pytest.raises(DemoError) as missing:
        validate(h, pid, "M9")
    assert missing.value.status == 404


def test_comment_reopens_the_milestone_and_the_task_goes_through_tests_first(
    h: Harness, pid: uuid.UUID
) -> None:
    build_all(h, pid)
    assert h.phase(pid) == "done"
    task = operate(
        h,
        pid,
        lambda db, p: demo.add_comment(db, emitter(h), p, "M1", "Make the title blue\nplease"),
    )
    assert isinstance(task, Task)
    assert task.ref == "C-001"
    assert h.phase(pid) == "building"
    c1 = h.tasks(pid)["C-001"]
    assert (c1.kind, c1.state, c1.milestone) == ("comment", "todo", "M1")
    assert c1.acceptance == ["Make the title blue\nplease"]
    assert c1.title.startswith("Comment on M1: Make the title blue")
    m1 = milestones(h, pid)["M1"]
    assert (m1.status, m1.tag, m1.validated_at) == ("pending", None, None)

    tick_until(h, pid, lambda: milestones(h, pid)["M1"].status == "built")
    assert [r.kind for r in h.runs("C-001", pid)] == ["test-writer", "worker"]
    assert h.states(pid)["C-001"] == "merged"
    m1 = milestones(h, pid)["M1"]
    assert m1.tag == "milestone-M1-r2"
    assert [r.ref for r in h.preview.deployed if r.milestone == "M1"] == [
        "milestone-M1",
        "milestone-M1-r2",
    ]
    assert h.preview.deployed[-1].ref == "milestone-M1-r2"
    validate(h, pid, "M1")
    assert h.phase(pid) == "done"


def test_second_comment_gets_the_next_reference(h: Harness, pid: uuid.UUID) -> None:
    build_all(h, pid)
    first = operate(h, pid, lambda db, p: demo.add_comment(db, emitter(h), p, "M1", "one"))
    second = operate(h, pid, lambda db, p: demo.add_comment(db, emitter(h), p, "M2", "two"))
    assert (first.ref, second.ref) == ("C-001", "C-002")  # type: ignore[attr-defined]


def test_comment_needs_a_built_or_validated_milestone(h: Harness, pid: uuid.UUID) -> None:
    h.start(pid)
    with pytest.raises(DemoError) as err:
        operate(h, pid, lambda db, p: demo.add_comment(db, emitter(h), p, "M1", "too early"))
    assert err.value.code == "wrong_state"


def test_revert_restores_the_previous_tag_and_rebuilds_later_milestones(
    h: Harness, pid: uuid.UUID
) -> None:
    build_all(h, pid)
    target = operate(h, pid, lambda db, p: demo.revert_target(db, p.id, "M2"))
    assert target == "milestone-M1"
    merges_before = len(h.git.merge_calls)
    ok = h.scheduler.run_revert_job(pid, "M2")
    assert ok
    assert h.phase(pid) == "building"
    ms = milestones(h, pid)
    assert ms["M1"].status == "validated"
    assert (ms["M2"].status, ms["M3"].status, ms["M2"].tag) == ("pending", "pending", None)
    tasks = h.tasks(pid)
    assert tasks["R-001"].kind == "revert" and tasks["R-001"].files == ["*"]
    m2_tasks = [t for t in tasks.values() if t.milestone in ("M2", "M3") and t.kind != "revert"]
    assert m2_tasks and all(t.state == "todo" and "R-001" in t.depends_on for t in m2_tasks)
    assert (pid, "M2") in h.preview.removed and (pid, "M3") in h.preview.removed

    tick_until(h, pid, lambda: all(m.status != "pending" for m in milestones(h, pid).values()))
    assert h.git.restores and h.git.restores[0][1] == "milestone-M1"
    assert h.states(pid)["R-001"] == "merged"
    assert milestones(h, pid)["M2"].tag == "milestone-M2-r2"
    # The restore went through a merge request like any other change.
    assert any(r.source_branch == "restore/milestone-M1" for r in h.git.merged)
    # Nothing of M2 was merged again before the restore was.
    assert h.git.merge_calls[merges_before].source_branch == "restore/milestone-M1"


def test_revert_of_the_first_milestone_goes_back_to_the_template(
    h: Harness, pid: uuid.UUID
) -> None:
    build_all(h, pid)
    assert operate(h, pid, lambda db, p: demo.revert_target(db, p.id, "M1")) == demo.TEMPLATE_TAG
    assert h.scheduler.run_revert_job(pid, "M1")
    assert {m.status for m in milestones(h, pid).values()} == {"pending"}
    tick_until(h, pid, lambda: h.states(pid).get("R-001") == "merged")
    assert h.git.restores[0][1] == demo.TEMPLATE_TAG


def test_revert_with_nothing_to_restore_does_not_open_a_merge_request(
    h: Harness, pid: uuid.UUID
) -> None:
    build_all(h, pid)
    h.git.restore_nothing = True
    h.scheduler.run_revert_job(pid, "M3")
    tick_until(h, pid, lambda: h.states(pid)["R-001"] == "merged")
    assert not any(r.source_branch.startswith("restore/") for r in h.git.merged)


def test_revert_is_idempotent_and_checks_the_state(h: Harness, pid: uuid.UUID) -> None:
    h.start(pid)
    with pytest.raises(DemoError):
        operate(h, pid, lambda db, p: demo.revert_target(db, p.id, "M1"))
    build_all(h, pid)
    assert h.scheduler.run_revert_job(pid, "M3")
    assert h.scheduler.run_revert_job(pid, "M3")  # replayed job: no second restore task
    assert [r for r in h.tasks(pid) if r.startswith("R-")] == ["R-001"]
    # M3 is pending now: a revert needs a built or validated milestone.
    with pytest.raises(DemoError):
        operate(h, pid, lambda db, p: demo.revert_target(db, p.id, "M3"))


def test_revert_stops_running_agents_of_the_reset_tasks(h: Harness, pid: uuid.UUID) -> None:
    h.agents.polls_before_done = 3
    h.start(pid)
    tick_until(h, pid, lambda: milestones(h, pid)["M1"].status == "built")
    # M2 work is in flight now: reverting M1 must stop it.
    running = [t for t in h.tasks(pid).values() if t.state in ("writing_tests", "implementing")]
    assert running
    h.scheduler.run_revert_job(pid, "M1")
    assert h.agents.stopped
    assert all(t.state == "todo" for t in h.tasks(pid).values() if t.kind != "revert")


def test_a_failed_restore_fails_the_task_and_blocks_the_rest(
    sessions: sessionmaker[Session], pid: uuid.UUID
) -> None:
    from cobble.capabilities.ci import CIState

    h = Harness(sessions, preview=FakePreviewProvider())
    build_all(h, pid)
    h.scheduler.run_revert_job(pid, "M3")
    repo = h.repo_ref(pid)
    h.ci.set_result(repo, "restore/milestone-M2", CIState.FAILURE, "boom")
    tick_until(h, pid, lambda: h.states(pid)["R-001"] == "failed")
    tick_until(h, pid, lambda: h.states(pid)["DEMO-M3"] == "blocked")
    assert h.started("R-001", "worker") == []  # no agent is ever asked to fix a restore


def test_milestone_events_reach_the_project_stream(h: Harness, pid: uuid.UUID) -> None:
    build_all(h, pid)
    events = [p for t, p in h.events(pid) if t == "milestone.updated"]
    assert {p["status"] for p in events} == {"built", "validated"}
    assert AgentOutcome.DONE.value == "done"
    with h.sessions() as db:
        rows = list(db.scalars(select(Milestone).where(Milestone.project_id == pid)))
    assert all(m.validated_at is not None for m in rows)
