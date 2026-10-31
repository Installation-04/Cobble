"""Create the `tasks` rows from the approved plan (idempotent)."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from cobble.db import Milestone, Plan, Task
from cobble.orchestrator.plan_schema import PlanInvalid, validate_plan


class NoApprovedPlan(Exception):
    """The project has no approved plan to turn into tasks."""


DEMO_FILES = ["app/seed.py"]
DEMO_ACCEPTANCE = [
    "app/seed.py fills an empty database with realistic, varied demo data "
    "(plausible names, dates and quantities; no lorem ipsum, no empty screens)",
    "seed() is idempotent: it adds data only when the tables are empty, never duplicates it",
    "the application still starts and its test suite still passes",
]


def demo_ref(milestone: str) -> str:
    return f"DEMO-{milestone}"


def materialize_tasks(session: Session, project_id: uuid.UUID, *, with_demo: bool = False) -> int:
    """Insert one task per plan task that has no row yet. Returns how many were created.

    The milestones of the plan get a row too. With `with_demo`, each milestone also gets the
    synthetic task `DEMO-Mx` that depends on all its tasks (ADR 0007).

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
    known = set(session.scalars(select(Milestone.ref).where(Milestone.project_id == project_id)))
    for milestone in parsed.milestones:
        if milestone.id not in known:
            session.add(Milestone(project_id=project_id, ref=milestone.id, title=milestone.title))
    if with_demo:
        for milestone in parsed.milestones:
            ref = demo_ref(milestone.id)
            if ref in existing:
                continue
            session.add(
                Task(
                    project_id=project_id,
                    ref=ref,
                    kind="demo",
                    title=f"Generate realistic demo data for {milestone.id}: {milestone.title}",
                    milestone=milestone.id,
                    depends_on=[t.id for t in parsed.tasks if t.milestone == milestone.id],
                    files=list(DEMO_FILES),
                    acceptance=list(DEMO_ACCEPTANCE),
                    tests="n/a",
                    size="S",
                    role="worker",
                )
            )
            created += 1
    session.flush()
    return created
