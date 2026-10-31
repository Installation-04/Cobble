"""Milestones, demo validation, comments and reverts (ADR 0007).

Plain functions over a database session so that both the API (validate, comment) and the
worker (revert, build) use the same rules. They never call git, CI or the preview service:
the scheduler does that. Every function is idempotent where a retry can happen.

Milestone life: `pending` -> `built` (all its tasks, including `DEMO-Mx`, are merged; the
scheduler tagged the default branch and deployed the tag) -> `validated`. A comment or a revert
re-opens it (`pending`, next `revision`, no tag).
"""

from __future__ import annotations

import contextlib
import re
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from cobble.db import Milestone, Project, Task, TaskRun
from cobble.events import publish_project

from . import rules

PENDING = "pending"
BUILT = "built"
VALIDATED = "validated"
MILESTONE_STATES = (PENDING, BUILT, VALIDATED)

TEMPLATE_TAG = "template-initial"  # the first commit of the repository (revert of M1)
RESTORE_PREFIX = "restore:"  # first acceptance item of a revert task: the tag to restore
COMMENT_TITLE_CHARS = 80

Emitter = Callable[[uuid.UUID, str, dict[str, Any]], None]


class DemoError(Exception):
    """A demo operation was refused; `code` is the machine-readable reason."""

    def __init__(self, status: int, code: str) -> None:
        super().__init__(code)
        self.status = status
        self.code = code


def redis_emitter(redis: Any) -> Emitter:
    def emit(project_id: uuid.UUID, event: str, payload: dict[str, Any]) -> None:
        if redis is not None:
            publish_project(redis, project_id, event, payload)

    return emit


def _now() -> datetime:
    return datetime.now(UTC)


def milestones_of(session: Session, project_id: uuid.UUID) -> list[Milestone]:
    rows = session.scalars(select(Milestone).where(Milestone.project_id == project_id))
    return sorted(rows, key=lambda m: rules.ref_key(m.ref))


def get_milestone(session: Session, project_id: uuid.UUID, ref: str) -> Milestone:
    found = session.scalars(
        select(Milestone).where(Milestone.project_id == project_id, Milestone.ref == ref)
    ).first()
    if found is None:
        raise DemoError(404, "not_found")
    return found


def tag_name(milestone: Milestone) -> str:
    base = f"milestone-{milestone.ref}"
    return base if milestone.revision == 0 else f"{base}-r{milestone.revision + 1}"


def emit_milestone(emit: Emitter, project_id: uuid.UUID, milestone: Milestone) -> None:
    emit(
        project_id,
        "milestone.updated",
        {
            "ref": milestone.ref,
            "status": milestone.status,
            "preview_state": milestone.preview_state,
        },
    )


def emit_task(emit: Emitter, task: Task) -> None:
    emit(
        task.project_id,
        "task.updated",
        {"task_id": task.ref, "state": task.state, "attempts": task.attempts},
    )


def _reopen(milestone: Milestone) -> None:
    milestone.status = PENDING
    milestone.tag = None
    milestone.preview_path = None
    milestone.preview_state = None
    milestone.built_at = None
    milestone.validated_at = None
    milestone.revision += 1


def _resume_building(session: Session, project: Project, emit: Emitter) -> None:
    if project.phase == "done":
        project.phase = "building"
        session.commit()
        emit(project.id, "phase.changed", {"phase": "building"})


# --- validate ---------------------------------------------------------------------------------


def validate_milestone(
    session: Session, emit: Emitter, project: Project, ref: str, *, now: datetime | None = None
) -> Milestone:
    milestone = get_milestone(session, project.id, ref)
    if milestone.status == VALIDATED:
        return milestone  # idempotent
    if milestone.status != BUILT:
        raise DemoError(409, "wrong_state")
    milestone.status = VALIDATED
    milestone.validated_at = now or _now()
    session.commit()
    emit_milestone(emit, project.id, milestone)
    finish_if_validated(session, emit, project)
    return milestone


def finish_if_validated(session: Session, emit: Emitter, project: Project) -> bool:
    """`building` -> `done` once every milestone is validated and every task is merged."""
    if project.phase != "building":
        return False
    milestones = milestones_of(session, project.id)
    states = [t.state for t in session.scalars(select(Task).where(Task.project_id == project.id))]
    if not milestones or any(m.status != VALIDATED for m in milestones):
        return False
    if not states or any(s != rules.MERGED for s in states):
        return False
    project.phase = "done"
    session.commit()
    emit(project.id, "phase.changed", {"phase": "done"})
    emit(project.id, "project.done", {"tasks": len(states)})
    return True


# --- comments ---------------------------------------------------------------------------------


def _next_ref(session: Session, project_id: uuid.UUID, prefix: str) -> str:
    refs = session.scalars(
        select(Task.ref).where(Task.project_id == project_id, Task.ref.like(f"{prefix}-%"))
    )
    numbers = [int(m.group(1)) for r in refs if (m := re.fullmatch(rf"{prefix}-(\d+)", r))]
    return f"{prefix}-{max(numbers, default=0) + 1:03d}"


def add_comment(session: Session, emit: Emitter, project: Project, ref: str, content: str) -> Task:
    """A comment on a demo becomes the task `C-001`... of that milestone and re-opens it."""
    milestone = get_milestone(session, project.id, ref)
    if milestone.status not in (BUILT, VALIDATED):
        raise DemoError(409, "wrong_state")
    task_ref = _next_ref(session, project.id, "C")
    first_line = content.strip().splitlines()[0] if content.strip() else ""
    task = Task(
        project_id=project.id,
        ref=task_ref,
        kind="comment",
        title=f"Comment on {ref}: {first_line[:COMMENT_TITLE_CHARS]}",
        milestone=ref,
        depends_on=[],
        files=[rules.ANY_FILE],
        acceptance=[content.strip()],
        tests=f"tests/test_{task_ref.lower().replace('-', '_')}.py",
        size="S",
        role="fullstack",
    )
    session.add(task)
    _reopen(milestone)
    session.flush()
    session.commit()
    emit_task(emit, task)
    emit_milestone(emit, project.id, milestone)
    _resume_building(session, project, emit)
    return task


# --- revert -----------------------------------------------------------------------------------


def revert_target(session: Session, project_id: uuid.UUID, ref: str) -> str:
    """The tag a revert of `ref` restores, or DemoError(409 wrong_state)."""
    milestones = milestones_of(session, project_id)
    index = next((i for i, m in enumerate(milestones) if m.ref == ref), None)
    if index is None:
        raise DemoError(404, "not_found")
    if milestones[index].status not in (BUILT, VALIDATED):
        raise DemoError(409, "wrong_state")
    if index == 0:
        return TEMPLATE_TAG
    previous = milestones[index - 1]
    if previous.status not in (BUILT, VALIDATED) or previous.tag is None:
        raise DemoError(409, "wrong_state")
    return previous.tag


def apply_revert(
    session: Session,
    emit: Emitter,
    project: Project,
    ref: str,
    stop_run: Callable[[str], None],
) -> list[str]:
    """Re-open `ref` and every later milestone, reset their tasks and queue the restore task.

    Returns the refs of the re-opened milestones (empty when it was already applied). The
    restore task `R-001`... (files `*`, so it runs alone) opens a merge request that brings
    the previous tag's tree back; the reset tasks depend on it. Runs of the reset tasks that
    are still going are stopped first (best effort; a leftover container ends by its time limit).
    """
    milestones = milestones_of(session, project.id)
    index = next((i for i, m in enumerate(milestones) if m.ref == ref), None)
    if index is None:
        raise DemoError(404, "not_found")
    if milestones[index].status == PENDING:
        return []  # already applied (a replayed job)
    tag = revert_target(session, project.id, ref)
    affected = milestones[index:]
    refs = {m.ref for m in affected}
    tasks = [
        t
        for t in session.scalars(select(Task).where(Task.project_id == project.id))
        if t.milestone in refs and t.kind != "revert"
    ]
    for task in tasks:
        for run in session.scalars(select(TaskRun).where(TaskRun.task_id == task.id)):
            if run.state in ("pending", "running") and run.agent_run_id:
                with contextlib.suppress(Exception):  # best effort: the run has a time limit
                    stop_run(run.agent_run_id)
    restore_ref = _next_ref(session, project.id, "R")
    restore = Task(
        project_id=project.id,
        ref=restore_ref,
        kind="revert",
        title=f"Restore {tag}",
        milestone=ref,
        depends_on=[],
        files=[rules.ANY_FILE],
        acceptance=[f"{RESTORE_PREFIX}{tag}"],
        tests="n/a",
        size="S",
        role="devops",
    )
    session.add(restore)
    for task in tasks:
        for run in session.scalars(select(TaskRun).where(TaskRun.task_id == task.id)):
            session.delete(run)
        task.state = rules.TODO
        task.attempts = 0
        task.escalated = False
        task.branch = None
        task.pr_number = None
        task.last_error = None
        task.depends_on = [*task.depends_on, restore_ref]
    for milestone in affected:
        _reopen(milestone)
    session.commit()
    emit_task(emit, restore)
    for task in tasks:
        emit_task(emit, task)
    for milestone in affected:
        emit_milestone(emit, project.id, milestone)
    _resume_building(session, project, emit)
    return [m.ref for m in affected]
