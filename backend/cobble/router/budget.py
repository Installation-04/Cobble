"""Per-project budget with a hard cap.

A project has an optional `budget_usd`. Before each LLM call the router checks that the
project is active; after each call the spend is compared to the budget:
  - at 80 %: publish `budget.warning` once,
  - at 100 %: pause the project and publish `budget.reached` once.
In-flight calls started before the cap was hit may overshoot it slightly.

A task has its own cap too (ADR 0021, `task_budget.py`): before each call of a task, its spend
so far is compared with a multiple of its estimate. Over the cap, the call is refused with
`TaskBudgetExceeded` (the project keeps running; the task's agent run fails and the task's
`last_error` says why). As for the project, a call already in flight still completes: a task
can overshoot its cap by one call.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from redis import Redis
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, sessionmaker

from cobble.config import Settings
from cobble.db import LLMCall, Project, Task
from cobble.events import publish, publish_project

from . import cost_settings, task_budget

WARNING_RATIO = Decimal("0.8")


class BudgetExceeded(Exception):
    def __init__(self, project_id: uuid.UUID) -> None:
        super().__init__(f"budget reached for project {project_id}")
        self.project_id = project_id


class TaskBudgetExceeded(BudgetExceeded):
    """One task reached its own cap (the project is still within its budget)."""

    def __init__(self, project_id: uuid.UUID, task_id: uuid.UUID) -> None:
        super().__init__(project_id)
        self.args = (f"task {task_id} reached its budget cap",)
        self.task_id = task_id


TASK_BUDGET_CODE = "task_budget_reached"


def spent(session: Session, project_id: uuid.UUID) -> Decimal:
    """What the project spent: the providers' charges, plus the estimated electricity of local
    models only when the owner chose to count it (ADR 0021)."""
    column: Any = LLMCall.cost_usd
    if cost_settings.read(session).electricity_counts_in_budget:
        column = column + func.coalesce(LLMCall.electricity_usd, 0)
    total = session.scalar(
        select(func.coalesce(func.sum(column), 0)).where(LLMCall.project_id == project_id)
    )
    return Decimal(str(total or 0))


class BudgetService:
    def __init__(
        self,
        sessions: sessionmaker[Session],
        events: Redis | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._sessions = sessions
        self._events = events
        self._settings = settings  # None: no per-task cap

    def ensure_can_spend(self, project_id: uuid.UUID, task_id: uuid.UUID | None = None) -> None:
        """Raise BudgetExceeded if the project is paused or already at its cap, and
        TaskBudgetExceeded if `task_id` already spent its own cap."""
        with self._sessions() as session:
            project = session.get(Project, project_id)
            if project is None:
                return
            if project.status != "active":
                raise BudgetExceeded(project_id)
            if project.budget_usd is not None and spent(session, project_id) >= project.budget_usd:
                self._pause(session, project)
                raise BudgetExceeded(project_id)
            if task_id is not None and self._settings is not None:
                self._ensure_task_within_cap(session, project_id, task_id, self._settings)

    def _ensure_task_within_cap(
        self, session: Session, project_id: uuid.UUID, task_id: uuid.UUID, settings: Settings
    ) -> None:
        facts = task_budget.task_facts(session, task_id)
        if facts is None or facts[0] != project_id:
            return
        _, ref, size = facts
        values = cost_settings.read(session)
        cap = task_budget.cap_for(
            task_budget.plan_estimate_doc(session, project_id), size, values, settings
        )
        if cap is None:
            return
        total = task_budget.task_spent(
            session, task_id, with_electricity=values.electricity_counts_in_budget
        )
        if total < cap:
            return
        task = session.get(Task, task_id)
        if task is not None and task.last_error != TASK_BUDGET_CODE:
            task.last_error = TASK_BUDGET_CODE
            session.commit()
            if self._events is not None:
                publish_project(
                    self._events,
                    project_id,
                    "task.budget_reached",
                    {"ref": ref, "spent_usd": str(total), "cap_usd": str(cap)},
                )
        raise TaskBudgetExceeded(project_id, task_id)

    def after_call(self, project_id: uuid.UUID) -> None:
        """Re-evaluate the budget after a recorded call; pause and publish on thresholds."""
        with self._sessions() as session:
            project = session.get(Project, project_id)
            if project is None or project.budget_usd is None:
                return
            total = spent(session, project_id)
            if total >= project.budget_usd:
                self._pause(session, project, total)
            elif total >= project.budget_usd * WARNING_RATIO:
                self._warn(session, project, total)

    def _warn(self, session: Session, project: Project, total: Decimal) -> None:
        result = session.execute(
            update(Project)
            .where(Project.id == project.id, Project.budget_warning_sent.is_(False))
            .values(budget_warning_sent=True)
        )
        session.commit()
        if result.rowcount == 1:  # type: ignore[attr-defined]
            self._publish("budget.warning", project, total)

    def _pause(self, session: Session, project: Project, total: Decimal | None = None) -> None:
        result = session.execute(
            update(Project)
            .where(Project.id == project.id, Project.status == "active")
            .values(status="paused")
        )
        session.commit()
        if result.rowcount == 1:  # type: ignore[attr-defined]
            if total is None:
                total = spent(session, project.id)
            self._publish("budget.reached", project, total)

    def _publish(self, event: str, project: Project, total: Decimal) -> None:
        if self._events is not None:
            publish(
                self._events,
                event,
                {
                    "project_id": str(project.id),
                    "spent_usd": str(total),
                    "budget_usd": str(project.budget_usd),
                },
            )


def apply_budget(session: Session, project: Project, budget_usd: Decimal | None) -> None:
    """Change a project's budget. Resumes a paused project if the new budget is above the spend."""
    project.budget_usd = budget_usd
    project.budget_warning_sent = False
    if project.status == "paused" and (
        budget_usd is None or spent(session, project.id) < budget_usd
    ):
        project.status = "active"
