"""Create the `tasks` rows from the approved plan (idempotent)."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from cobble.db import Plan, Task
from cobble.orchestrator.plan_schema import PlanInvalid, validate_plan


class NoApprovedPlan(Exception):
    """The project has no approved plan to turn into tasks."""


def materialize_tasks(session: Session, project_id: uuid.UUID) -> int:
    """Insert one task per plan task that has no row yet. Returns how many were created.

    Existing rows are never touched, so calling this again (a restart in the middle of
    `start_project`) cannot reset a task that already progressed.
    """
    plan = session.scalars(
        select(Plan)
        .where(Plan.project_id == project_id, Plan.status == "approved")
        .order_by(Plan.version.desc())
        .limit(1)
    ).first()
    if plan is None:
        raise NoApprovedPlan(str(project_id))
    try:
        parsed = validate_plan(plan.plan)
    except PlanInvalid as exc:  # approved plans were validated, so this is corruption
        raise NoApprovedPlan(str(exc)) from exc
    existing = set(session.scalars(select(Task.ref).where(Task.project_id == project_id)))
    created = 0
    for item in parsed.tasks:
        if item.id in existing:
            continue
        session.add(
            Task(
                project_id=project_id,
                ref=item.id,
                title=item.title,
                milestone=item.milestone,
                depends_on=list(item.depends_on),
                files=list(item.files),
                acceptance=list(item.acceptance),
                tests=item.tests,
                size=item.size,
                role=item.role,
            )
        )
        created += 1
    session.flush()
    return created
