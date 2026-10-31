"""Operator controls on a task: pause, resume, stop, retry (ADR 0007).

`decide` is a pure function from an action and the facts about a task to a `Decision`; `apply`
is the thin I/O shell around it (database, agent runner, event). Every action is idempotent:
asking again for what already holds changes nothing and succeeds.

State machine (rows: action, columns: current state of the task):

    state                | pause        | resume   | stop    | retry
    ---------------------+--------------+----------+---------+----------------
    todo                 | paused(hold) | no-op    | stopped | no-op
    writing_tests        | paused(hold) | no-op    | stopped | 409
    implementing         | paused(hold) | no-op    | stopped | 409
    ci                   | paused(hold) | no-op    | stopped | 409
    paused (held)        | no-op        | continue | stopped | todo (*)
    paused (waiting)     | paused(hold) | no-op    | stopped | todo (*)
    stopped              | 409          | 409      | no-op   | todo
    failed, blocked      | 409          | 409      | 409     | todo
    merged               | 409          | 409      | 409     | 409

    (*) 409 while a run is still active: stop it first.

`paused` has two meanings. The scheduler parks a task as `paused` while it waits for a free slot
or for the budget (the scheduler restarts it by itself). A pause requested by the operator holds
the task: the scheduler leaves it alone until `resume`. The hold is recorded as a prefix of
`last_error` (no schema change). A run that is already running when the task is paused keeps
going, but nobody follows it until `resume` re-attaches it.

* `resume` returns the task to the state it can continue from: its running state when a run is
  still active, `ci` when its last worker run finished and a merge request exists, `implementing`
  when it finished without one, `todo` when it never ran, otherwise `paused` (waiting), so the
  scheduler starts the next run when a slot is free.
* `stop` ends the active run (the caller asks the agent service) and closes its row as `stopped`.
* `retry` resets attempts, escalation and the last error, forgets the merge request number, marks
  the previous failed/finished runs `retired` so they no longer count as attempts, keeps the
  branch, and moves the task to `todo`. Tasks blocked only because of this task go back to
  `todo` too.
"""

from __future__ import annotations

import enum
import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

from redis import Redis
from sqlalchemy import select
from sqlalchemy.orm import Session

from cobble.capabilities.agent import AgentRunner, AgentUnavailable
from cobble.db import Task, TaskRun
from cobble.events import publish_project

from . import rules

log = logging.getLogger(__name__)

USER_PAUSED = "user_paused"  # prefix of `last_error` while the operator holds a paused task
HELD = "held"  # how the engine sees a held task: not a candidate, takes no files
DEPENDENCY_FAILED = "dependency_failed"

RUN_PENDING = "pending"
RUN_RUNNING = "running"
RUN_STOPPED = "stopped"
RUN_RETIRED = "retired"
ACTIVE_RUNS = (RUN_PENDING, RUN_RUNNING)
# Run states that used up an attempt (mirrors the scheduler's COUNTED, plus nothing else).
_RETIRABLE = ("done", "failed", "timeout", "loop_detected", "rejected")


class Action(enum.StrEnum):
    PAUSE = "pause"
    RESUME = "resume"
    STOP = "stop"
    RETRY = "retry"


class WrongState(Exception):
    """The action is not allowed in the task's current state (HTTP 409 `wrong_state`)."""

    def __init__(self, action: Action, state: str) -> None:
        super().__init__(f"cannot {action.value} a task that is {state}")
        self.action = action
        self.state = state


# --- the user hold ------------------------------------------------------------------------


def is_held(state: str, last_error: str | None) -> bool:
    return state == rules.PAUSED and last_error is not None and last_error.startswith(USER_PAUSED)


def _hold(last_error: str | None) -> str:
    if last_error is not None and last_error.startswith(USER_PAUSED):
        return last_error
    return USER_PAUSED + (f"\n{last_error}" if last_error else "")


def _release(last_error: str | None) -> str | None:
    if last_error is None or not last_error.startswith(USER_PAUSED):
        return last_error
    return last_error.removeprefix(USER_PAUSED).lstrip("\n") or None


# --- pure decision ------------------------------------------------------------------------


@dataclass(frozen=True)
class RunFact:
    kind: str  # test-writer | worker
    state: str


@dataclass(frozen=True)
class TaskFacts:
    state: str
    last_error: str | None = None
    pr_number: int | None = None
    runs: tuple[RunFact, ...] = ()  # oldest first

    @property
    def active_run(self) -> bool:
        return any(r.state in ACTIVE_RUNS for r in self.runs)


@dataclass(frozen=True)
class Decision:
    state: str
    last_error: str | None
    changed: bool  # False: nothing to write, nothing to publish
    stop_runs: bool = False  # stop (and close) the active runs
    retire_runs: bool = False
    reset: bool = False  # attempts, escalated, pr_number back to their initial values
    unblock: bool = False  # tasks blocked by this one go back to todo


def resume_state(facts: TaskFacts) -> str:
    """The state a held task continues from (see the module docstring)."""
    last = facts.runs[-1] if facts.runs else None
    if last is None:
        return rules.TODO
    if last.state in ACTIVE_RUNS:
        return rules.IMPLEMENTING if last.kind == "worker" else rules.WRITING_TESTS
    if last.kind == "worker" and last.state == "done":
        return rules.CI if facts.pr_number is not None else rules.IMPLEMENTING
    return rules.PAUSED


_RUNNING_OR_TODO = (rules.TODO, rules.WRITING_TESTS, rules.IMPLEMENTING, rules.CI)


def decide(action: Action, facts: TaskFacts) -> Decision:
    """What `action` does to a task. Raises WrongState when it is not allowed."""
    state, error = facts.state, facts.last_error
    keep = Decision(state, error, changed=False)

    if action is Action.PAUSE:
        if state in _RUNNING_OR_TODO:
            return Decision(rules.PAUSED, _hold(error), changed=True)
        if state == rules.PAUSED:
            held = _hold(error)
            return keep if held == error else Decision(state, held, changed=True)
        raise WrongState(action, state)

    if action is Action.RESUME:
        if is_held(state, error):
            return Decision(resume_state(facts), _release(error), changed=True)
        if state in _RUNNING_OR_TODO or state == rules.PAUSED:
            return keep
        raise WrongState(action, state)

    if action is Action.STOP:
        if state == rules.STOPPED:
            return keep
        if state in _RUNNING_OR_TODO or state == rules.PAUSED:
            return Decision(rules.STOPPED, _release(error), changed=True, stop_runs=True)
        raise WrongState(action, state)

    # retry
    if state == rules.TODO:
        return keep
    if state in (rules.FAILED, rules.BLOCKED, rules.STOPPED) or (
        state == rules.PAUSED and not facts.active_run
    ):
        return Decision(rules.TODO, None, changed=True, retire_runs=True, reset=True, unblock=True)
    raise WrongState(action, state)


def blocked_by(
    retried: str, tasks: Sequence[tuple[str, str, str | None, Sequence[str]]]
) -> list[str]:
    """Refs of the `blocked` tasks that only wait on `retried`, directly or not.

    `tasks` are `(ref, state, last_error, depends_on)`. A blocked task stays blocked while one
    of its dependencies is still failed or blocked for another reason.
    """
    by_ref = {ref: (state, error, tuple(deps)) for ref, state, error, deps in tasks}
    freed = {retried}
    changed = True
    while changed:
        changed = False
        for ref, (state, error, deps) in by_ref.items():
            if ref in freed or state != rules.BLOCKED or error != DEPENDENCY_FAILED:
                continue
            if any(dep in freed for dep in deps):
                freed.add(ref)
                changed = True
    freed.discard(retried)
    return sorted(freed, key=rules.ref_key)


# --- the I/O shell ------------------------------------------------------------------------


@dataclass
class Outcome:
    task: Task
    changed: bool
    unblocked: list[str] = field(default_factory=list)


def _facts(task: Task, runs: Sequence[TaskRun]) -> TaskFacts:
    return TaskFacts(
        task.state,
        task.last_error,
        task.pr_number,
        tuple(RunFact(r.kind, r.state) for r in runs),
    )


def _emit(redis: Redis | None, task: Task) -> None:
    if redis is not None:
        publish_project(
            redis,
            task.project_id,
            "task.updated",
            {"task_id": task.ref, "state": task.state, "attempts": task.attempts},
        )


def apply(
    session: Session,
    task: Task,
    action: Action,
    *,
    agents: AgentRunner | None = None,
    redis: Redis | None = None,
) -> Outcome:
    """Run `action` on `task` and commit. Raises WrongState; lets AgentUnavailable through
    (nothing is changed then, so the caller can simply try again)."""
    runs = list(
        session.scalars(
            select(TaskRun).where(TaskRun.task_id == task.id).order_by(TaskRun.started_at)
        )
    )
    decision = decide(action, _facts(task, runs))
    if not decision.changed:
        return Outcome(task, False)

    if decision.stop_runs:
        for run in runs:
            if run.state in ACTIVE_RUNS and run.agent_run_id is not None:
                if agents is None:
                    raise AgentUnavailable("no agent service is configured to stop the run")
                agents.stop(run.agent_run_id)  # may raise AgentUnavailable: nothing changed yet
        for run in runs:
            if run.state in ACTIVE_RUNS:
                run.state = RUN_STOPPED
                if run.finished_at is None:
                    run.finished_at = datetime.now(UTC)
    if decision.retire_runs:
        for run in runs:
            if run.state in _RETIRABLE and not (run.kind == "test-writer" and run.state == "done"):
                run.state = RUN_RETIRED

    unblocked: list[str] = []
    if decision.unblock:
        rows = session.scalars(select(Task).where(Task.project_id == task.project_id)).all()
        freed = blocked_by(
            task.ref, [(t.ref, t.state, t.last_error, list(t.depends_on)) for t in rows]
        )
        for other in rows:
            if other.ref in freed:
                other.state = rules.TODO
                other.last_error = None
                unblocked.append(other.ref)

    previous = task.state
    task.state = decision.state
    task.last_error = decision.last_error
    if decision.reset:
        task.attempts = 0
        task.escalated = False
        task.pr_number = None
    session.commit()
    if previous != task.state or decision.reset:
        _emit(redis, task)
    for ref in unblocked:
        other = session.scalars(
            select(Task).where(Task.project_id == task.project_id, Task.ref == ref)
        ).one()
        _emit(redis, other)
    return Outcome(task, True, unblocked)


__all__ = [
    "ACTIVE_RUNS",
    "HELD",
    "Action",
    "Decision",
    "Outcome",
    "RunFact",
    "TaskFacts",
    "WrongState",
    "apply",
    "blocked_by",
    "decide",
    "is_held",
    "resume_state",
]
