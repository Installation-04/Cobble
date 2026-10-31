"""Per-project budget with a hard cap.

A project has an optional `budget_usd`. Before each LLM call the router checks that the
project is active; after each call the spend is compared to the budget:
  - at 80 %: publish `budget.warning` once,
  - at 100 %: pause the project and publish `budget.reached` once.
In-flight calls started before the cap was hit may overshoot it slightly.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from redis import Redis
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, sessionmaker

from cobble.db import LLMCall, Project
from cobble.events import publish

WARNING_RATIO = Decimal("0.8")


class BudgetExceeded(Exception):
    def __init__(self, project_id: uuid.UUID) -> None:
        super().__init__(f"budget reached for project {project_id}")
        self.project_id = project_id


def spent(session: Session, project_id: uuid.UUID) -> Decimal:
    total = session.scalar(
        select(func.coalesce(func.sum(LLMCall.cost_usd), 0)).where(LLMCall.project_id == project_id)
    )
    return Decimal(total or 0)


class BudgetService:
    def __init__(self, sessions: sessionmaker[Session], events: Redis | None = None) -> None:
        self._sessions = sessions
        self._events = events

    def ensure_can_spend(self, project_id: uuid.UUID) -> None:
        """Raise BudgetExceeded if the project is paused or already at its cap."""
        with self._sessions() as session:
            project = session.get(Project, project_id)
            if project is None:
                return
            if project.status != "active":
                raise BudgetExceeded(project_id)
            if project.budget_usd is not None and spent(session, project_id) >= project.budget_usd:
                self._pause(session, project)
                raise BudgetExceeded(project_id)

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
