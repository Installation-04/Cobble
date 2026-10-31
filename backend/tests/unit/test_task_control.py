"""Pause / resume / stop / retry: the pure decision table, then the scheduler honouring it."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from cobble.capabilities.agent import AgentOutcome, AgentUnavailable
from cobble.capabilities.fakes import FakeAgentRunner
from cobble.db import Task, TaskRun
from cobble.scheduler import control, rules
from cobble.scheduler.control import Action, RunFact, TaskFacts, WrongState, decide

from .scheduling import Harness, make_ready_project

P, R, S, T = Action.PAUSE, Action.RESUME, Action.STOP, Action.RETRY
HOLD = control.USER_PAUSED


def facts(
    state: str, error: str | None = None, pr: int | None = None, *runs: tuple[str, str]
) -> TaskFacts:
    return TaskFacts(state, error, pr, tuple(RunFact(k, s) for k, s in runs))


# --- decide: the table -------------------------------------------------------------------

# (action, state, last_error) -> (new state, held?) ; None = 409 ; "same" = no-op
TABLE: list[tuple[Action, str, str | None, str | None]] = [
    (P, "todo", None, "paused"),
    (P, "writing_tests", None, "paused"),
    (P, "implementing", None, "paused"),
    (P, "ci", None, "paused"),
    (P, "paused", HOLD, "same"),
    (P, "paused", None, "paused"),  # a waiting task becomes held
    (P, "stopped", None, None),
    (P, "failed", None, None),
    (P, "blocked", None, None),
    (P, "merged", None, None),
    (R, "paused", HOLD, "continue"),
    (R, "paused", None, "same"),
    (R, "todo", None, "same"),
    (R, "writing_tests", None, "same"),
    (R, "implementing", None, "same"),
    (R, "ci", None, "same"),
    (R, "stopped", None, None),
    (R, "failed", None, None),
    (R, "blocked", None, None),
    (R, "merged", None, None),
    (S, "todo", None, "stopped"),
    (S, "writing_tests", None, "stopped"),
    (S, "implementing", None, "stopped"),
    (S, "ci", None, "stopped"),
    (S, "paused", HOLD, "stopped"),
    (S, "paused", None, "stopped"),
    (S, "stopped", None, "same"),
    (S, "failed", None, None),
    (S, "blocked", None, None),
    (S, "merged", None, None),
    (T, "todo", None, "same"),
    (T, "writing_tests", None, None),
    (T, "implementing", None, None),
    (T, "ci", None, None),
    (T, "paused", HOLD, "todo"),
    (T, "paused", None, "todo"),
    (T, "stopped", None, "todo"),
    (T, "failed", "boom", "todo"),
    (T, "blocked", "dependency_failed", "todo"),
    (T, "merged", None, None),
]


@pytest.mark.parametrize(("action", "state", "error", "expected"), TABLE)
def test_decision_table(
    action: Action, state: str, error: str | None, expected: str | None
) -> None:
    if expected is None:
        with pytest.raises(WrongState) as raised:
            decide(action, facts(state, error))
        assert raised.value.state == state
        return
    decision = decide(action, facts(state, error))
    if expected == "same":
        assert (decision.changed, decision.state, decision.last_error) == (False, state, error)
    elif expected == "continue":
        assert decision.changed
        assert decision.state != "paused" or not control.is_held("paused", decision.last_error)
        assert not control.is_held(decision.state, decision.last_error)
    else:
        assert decision.changed
        assert decision.state == expected
        assert control.is_held(decision.state, decision.last_error) == (action is P)


def test_every_state_and_action_is_covered() -> None:
    covered = {(a, s) for a, s, _e, _x in TABLE}
    assert covered == {(a, s) for a in Action for s in rules.TASK_STATES}


def test_all_actions_are_idempotent() -> None:
    """Applying the decision's result again changes nothing (or is the same transition)."""
    for action, state, error, expected in TABLE:
        if expected is None:
            continue
        first = decide(action, facts(state, error))
        again = decide(action, facts(first.state, first.last_error))
        assert not again.changed, (action, state)


def test_pause_keeps_the_previous_error_and_resume_gives_it_back() -> None:
    held = decide(P, facts("implementing", "agent failed: oops"))
    assert held.last_error == f"{HOLD}\nagent failed: oops"
    assert decide(P, facts("paused", held.last_error)).changed is False
    back = decide(R, facts("paused", held.last_error, None, ("worker", "failed")))
    assert back.last_error == "agent failed: oops"
    assert decide(P, facts("todo")).last_error == HOLD
    assert decide(R, facts("paused", HOLD)).last_error is None


RESUME_CASES = [
    ((), None, "todo"),
    ((("test-writer", "running"),), None, "writing_tests"),
    ((("test-writer", "done"), ("worker", "running")), None, "implementing"),
    ((("test-writer", "done"), ("worker", "pending")), None, "implementing"),
    ((("test-writer", "done"), ("worker", "done")), 7, "ci"),
    ((("test-writer", "done"), ("worker", "done")), None, "implementing"),
    ((("test-writer", "done"), ("worker", "rejected")), 7, "paused"),
    ((("test-writer", "done"), ("worker", "failed")), None, "paused"),
    ((("test-writer", "done"),), None, "paused"),
]


@pytest.mark.parametrize(("runs", "pr", "expected"), RESUME_CASES)
def test_resume_goes_back_to_where_the_task_can_continue(
    runs: tuple[tuple[str, str], ...], pr: int | None, expected: str
) -> None:
    decision = decide(R, facts("paused", HOLD, pr, *runs))
    assert decision.state == expected
    assert not control.is_held(decision.state, decision.last_error)


def test_stop_and_retry_flags() -> None:
    stop = decide(S, facts("implementing", None, None, ("worker", "running")))
    assert (stop.stop_runs, stop.retire_runs, stop.reset) == (True, False, False)
    retry = decide(T, facts("failed", "x", 3, ("worker", "failed")))
    assert (retry.state, retry.last_error, retry.retire_runs, retry.reset, retry.unblock) == (
        "todo",
        None,
        True,
        True,
        True,
    )


def test_retry_of_a_paused_task_needs_the_run_to_be_over() -> None:
    with pytest.raises(WrongState):
        decide(T, facts("paused", HOLD, None, ("worker", "running")))
    assert decide(T, facts("paused", HOLD, None, ("worker", "failed"))).state == "todo"


def test_blocked_by_follows_the_chain_but_not_other_causes() -> None:
    tasks: list[tuple[str, str, str | None, list[str]]] = [
        ("T-001", "failed", "x", []),
        ("T-002", "blocked", "dependency_failed", ["T-001"]),
        ("T-003", "blocked", "dependency_failed", ["T-002"]),
        ("T-004", "blocked", "dependency_failed", ["T-002", "T-009"]),
        ("T-005", "blocked", "dependency_failed", ["T-009"]),
        ("T-006", "todo", None, ["T-001"]),
        ("T-009", "failed", "y", []),
    ]
    # T-004 depends on T-009 as well, but the engine blocks on any dead dependency: it is
    # freed with T-002 and blocked again on the next tick if T-009 is still dead.
    assert control.blocked_by("T-001", tasks) == ["T-002", "T-003", "T-004"]
    assert control.blocked_by("T-009", tasks) == ["T-004", "T-005"]


# --- apply: database, runner, event -------------------------------------------------------


@pytest.fixture
def pid(sessions: sessionmaker[Session]) -> uuid.UUID:
    return make_ready_project(sessions)


def do(harness: Harness, pid: uuid.UUID, ref: str, action: Action, **kw: Any) -> control.Outcome:
    with harness.sessions() as db:
        task = db.scalars(select(Task).where(Task.project_id == pid, Task.ref == ref)).one()
        agents = kw.pop("agents", harness.agents)
        return control.apply(db, task, action, agents=agents, redis=harness.redis, **kw)


def slow_harness(sessions: sessionmaker[Session], polls: int = 1000) -> Harness:
    return Harness(sessions, agents=FakeAgentRunner(polls_before_done=polls))


def test_stop_stops_the_run_closes_its_row_and_publishes(
    sessions: sessionmaker[Session], pid: uuid.UUID
) -> None:
    harness = slow_harness(sessions)
    harness.start(pid)
    harness.scheduler.tick()
    assert harness.states(pid)["T-001"] == "writing_tests"

    outcome = do(harness, pid, "T-001", S)
    assert outcome.changed
    assert harness.agents.stopped == ["run-1"]
    run = harness.runs("T-001", pid)[0]
    assert (run.state, run.finished_at is not None) == ("stopped", True)
    assert harness.states(pid)["T-001"] == "stopped"
    assert ("task.updated", {"task_id": "T-001", "state": "stopped", "attempts": 0}) in (
        harness.events(pid)
    )

    again = do(harness, pid, "T-001", S)  # idempotent: no second stop, no second event
    assert not again.changed
    assert harness.agents.stopped == ["run-1"]


def test_stop_keeps_the_task_if_the_agent_service_is_down(
    sessions: sessionmaker[Session], pid: uuid.UUID
) -> None:
    harness = slow_harness(sessions)
    harness.start(pid)
    harness.scheduler.tick()

    class Down(FakeAgentRunner):
        def stop(self, run_id: str) -> None:
            raise AgentUnavailable("down")

    with pytest.raises(AgentUnavailable):
        do(harness, pid, "T-001", S, agents=Down())
    assert harness.states(pid)["T-001"] == "writing_tests"
    assert harness.runs("T-001", pid)[0].state == "running"
    with pytest.raises(AgentUnavailable):  # no runner at all behaves the same
        do(harness, pid, "T-001", S, agents=None)
    assert harness.states(pid)["T-001"] == "writing_tests"


def test_stopping_a_task_without_a_run_needs_no_runner(
    sessions: sessionmaker[Session], pid: uuid.UUID
) -> None:
    harness = slow_harness(sessions)
    harness.start(pid)
    assert do(harness, pid, "T-003", S, agents=None).changed
    assert harness.states(pid)["T-003"] == "stopped"


def test_a_stopped_task_is_never_restarted(sessions: sessionmaker[Session], pid: uuid.UUID) -> None:
    harness = slow_harness(sessions)
    harness.start(pid)
    harness.scheduler.tick()
    do(harness, pid, "T-001", S)
    started = len(harness.agents.runs)
    for _ in range(15):
        harness.scheduler.tick()
    harness.scheduler.reconcile()
    harness.new_scheduler().reconcile()
    for _ in range(5):
        harness.scheduler.tick()
    states = harness.states(pid)
    assert states["T-001"] == "stopped"
    assert len(harness.agents.runs) == started
    assert harness.started("T-001", "worker") == []
    assert all(states[f"T-{n:03d}"] == "todo" for n in range(2, 12) if n != 1)
    assert harness.phase(pid) == "building"


def test_a_paused_task_waits_until_it_is_resumed(
    sessions: sessionmaker[Session], pid: uuid.UUID
) -> None:
    harness = Harness(sessions)
    harness.start(pid)
    do(harness, pid, "T-001", P)  # held before it ever ran
    for _ in range(15):
        harness.scheduler.tick()
    assert harness.states(pid)["T-001"] == "paused"
    assert harness.agents.runs == []
    assert harness.phase(pid) == "building"

    do(harness, pid, "T-001", R)
    assert harness.states(pid)["T-001"] == "todo"
    harness.run_until(pid)
    assert set(harness.states(pid).values()) == {"merged"}


def test_a_run_started_before_the_pause_is_picked_up_again_on_resume(
    sessions: sessionmaker[Session], pid: uuid.UUID
) -> None:
    harness = slow_harness(sessions, polls=2)
    harness.start(pid)
    harness.scheduler.tick()
    assert harness.states(pid)["T-001"] == "writing_tests"
    do(harness, pid, "T-001", P)
    for _ in range(10):
        harness.scheduler.tick()
    assert harness.states(pid)["T-001"] == "paused"
    assert harness.agents._polls["run-1"] == 0  # nobody follows the run while paused
    assert harness.runs("T-001", pid)[0].state == "running"

    do(harness, pid, "T-001", R)
    assert harness.states(pid)["T-001"] == "writing_tests"
    harness.run_until(pid)
    assert set(harness.states(pid).values()) == {"merged"}


def test_a_paused_task_does_not_let_a_neighbour_jump_the_queue_forever(
    sessions: sessionmaker[Session], pid: uuid.UUID
) -> None:
    """A held task takes no files and is not a candidate; the others carry on around it."""
    harness = Harness(sessions)
    harness.start(pid)
    harness.scheduler.tick()
    do(harness, pid, "T-003", P)
    harness.tick_until_settled(pid)
    states = harness.states(pid)
    assert states["T-003"] == "paused"
    assert states["T-001"] == states["T-002"] == "merged"
    assert states["T-003"] == "paused" and "todo" in states.values()
    do(harness, pid, "T-003", R)
    harness.run_until(pid)


def test_pause_from_ci_then_resume_goes_back_to_ci(
    sessions: sessionmaker[Session], pid: uuid.UUID
) -> None:
    from cobble.capabilities.ci import CIState

    harness = Harness(sessions)
    harness.ci.default = CIState.PENDING
    harness.start(pid)
    for _ in range(8):
        harness.scheduler.tick()
    assert harness.states(pid)["T-001"] == "ci"
    do(harness, pid, "T-001", P)
    for _ in range(5):
        harness.scheduler.tick()
    assert harness.states(pid)["T-001"] == "paused"
    assert harness.git.merged == []
    do(harness, pid, "T-001", R)
    assert harness.states(pid)["T-001"] == "ci"
    harness.ci.default = CIState.SUCCESS
    harness.run_until(pid)


def test_retry_a_failed_task_gives_it_fresh_attempts_and_unblocks_dependents(
    sessions: sessionmaker[Session], pid: uuid.UUID
) -> None:
    bad = {("T-001", "worker", n): AgentOutcome.FAILED for n in range(1, 5)}
    harness = Harness(sessions, agents=FakeAgentRunner(script=bad))
    harness.start(pid)
    harness.scheduler.tick()
    harness.tick_until_settled(pid)
    states = harness.states(pid)
    assert states["T-001"] == "failed"
    assert states["T-002"] == "blocked"
    assert harness.tasks(pid)["T-001"].attempts == 4

    harness.agents.script.clear()  # the fault is fixed
    outcome = do(harness, pid, "T-001", T)
    assert outcome.changed
    assert "T-002" in outcome.unblocked
    task = harness.tasks(pid)["T-001"]
    assert (task.state, task.attempts, task.escalated, task.last_error, task.pr_number) == (
        "todo",
        0,
        False,
        None,
        None,
    )
    assert {r.state for r in harness.runs("T-001", pid) if r.kind == "worker"} == {"retired"}
    harness.run_until(pid)
    assert set(harness.states(pid).values()) == {"merged"}
    assert harness.tasks(pid)["T-001"].attempts == 1


def test_retry_of_a_stopped_task_and_refusals(
    sessions: sessionmaker[Session], pid: uuid.UUID
) -> None:
    harness = slow_harness(sessions, polls=1)
    harness.start(pid)
    harness.scheduler.tick()
    with pytest.raises(WrongState):
        do(harness, pid, "T-001", T)  # still running: stop it first
    do(harness, pid, "T-001", S)
    assert do(harness, pid, "T-001", T).changed
    assert not do(harness, pid, "T-001", T).changed  # idempotent
    harness.run_until(pid)
    for action in Action:  # merged: nothing is allowed
        with pytest.raises(WrongState):
            do(harness, pid, "T-001", action)


def test_retired_runs_keep_their_logs(sessions: sessionmaker[Session], pid: uuid.UUID) -> None:
    bad = {("T-001", "worker", n): AgentOutcome.FAILED for n in range(1, 5)}
    harness = Harness(sessions, agents=FakeAgentRunner(script=bad))
    harness.start(pid)
    harness.tick_until_settled(pid)
    do(harness, pid, "T-001", T)
    with sessions() as db:
        runs = list(db.scalars(select(TaskRun).where(TaskRun.state == "retired")))
    assert len(runs) == 4
    assert all(r.log_tail for r in runs)
