"""Spend reports computed in SQL over `llm_calls` (ADR 0007).

Every figure comes from grouped queries (three per project, one for the global view), never
from a loop over calls or tasks. Money is a `Decimal` all the way and leaves as a string with
2 to 8 decimals.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.orm import Session

from cobble.db import LLMCall, Plan, Project, Task
from cobble.scheduler.rules import ref_key

_EIGHT = Decimal("0.00000001")
_TWO = Decimal("0.01")


def money(value: Decimal | float | int | str | None) -> str:
    """`value` as a string with at least 2 and at most 8 decimals ("0.30", "0.01234567")."""
    amount = Decimal(str(value or 0)).quantize(_EIGHT)
    text = format(amount, "f").rstrip("0")
    whole, _, fraction = text.partition(".")
    return f"{whole}.{fraction.ljust(2, '0')}"


@dataclass(frozen=True)
class Totals:
    cost: Decimal
    prompt_tokens: int
    completion_tokens: int
    calls: int


def _row(cost: Any, prompt: Any, completion: Any, calls: Any) -> Totals:
    return Totals(Decimal(str(cost or 0)), int(prompt or 0), int(completion or 0), int(calls or 0))


def _aggregates() -> tuple[ColumnElement[Any], ...]:
    return (
        func.coalesce(func.sum(LLMCall.cost_usd), 0),
        func.coalesce(func.sum(LLMCall.prompt_tokens), 0),
        func.coalesce(func.sum(LLMCall.completion_tokens), 0),
        func.count(LLMCall.id),
    )


def _entry(key: str, name: str | None, totals: Totals) -> dict[str, Any]:
    return {
        key: name,
        "cost_usd": money(totals.cost),
        "prompt_tokens": totals.prompt_tokens,
        "completion_tokens": totals.completion_tokens,
        "calls": totals.calls,
    }


def _by_cost(rows: list[tuple[str | None, Totals]]) -> list[tuple[str | None, Totals]]:
    return sorted(rows, key=lambda r: (-r[1].cost, r[0] or ""))


def plan_estimate(session: Session, project_id: uuid.UUID) -> Decimal | None:
    """`estimate.cost_usd` of the approved plan (the latest version), else of the latest plan."""
    plans = session.execute(
        select(Plan.estimate, Plan.status)
        .where(Plan.project_id == project_id)
        .order_by(Plan.version.desc())
    ).all()
    for wanted in ("approved", None):
        for estimate, status in plans:
            if wanted is None or status == wanted:
                value = estimate.get("cost_usd") if isinstance(estimate, dict) else None
                if value is None:
                    continue
                try:
                    return Decimal(str(value))
                except ArithmeticError:
                    continue
    return None


def project_costs(session: Session, project: Project) -> dict[str, Any]:
    """The `GET /projects/{id}/costs` body."""
    where = LLMCall.project_id == project.id
    by_task_rows = session.execute(
        select(Task.ref, *_aggregates())
        .select_from(LLMCall)
        .outerjoin(Task, Task.id == LLMCall.task_id)
        .where(where)
        .group_by(Task.ref)
    ).all()
    by_model_rows = session.execute(
        select(LLMCall.model, *_aggregates()).where(where).group_by(LLMCall.model)
    ).all()
    by_role_rows = session.execute(
        select(LLMCall.role, *_aggregates()).where(where).group_by(LLMCall.role)
    ).all()

    tasks = sorted(
        ((r[0], _row(*r[1:])) for r in by_task_rows),
        key=lambda r: (r[0] is None, ref_key(r[0]) if r[0] else (0, "")),
    )
    models = _by_cost([(r[0], _row(*r[1:])) for r in by_model_rows])
    roles = _by_cost([(r[0], _row(*r[1:])) for r in by_role_rows])
    spent = sum((t.cost for _, t in models), Decimal(0))
    estimate = plan_estimate(session, project.id)
    return {
        "budget_usd": money(project.budget_usd) if project.budget_usd is not None else None,
        "spent_usd": money(spent),
        "tokens": {
            "prompt": sum(t.prompt_tokens for _, t in models),
            "completion": sum(t.completion_tokens for _, t in models),
        },
        "estimate_usd": money(estimate) if estimate is not None else None,
        "by_task": [_entry("ref", name, t) for name, t in tasks],
        "by_model": [_entry("model", name, t) for name, t in models],
        "by_role": [_entry("role", name, t) for name, t in roles],
    }


def global_costs(session: Session, owner_id: uuid.UUID) -> list[dict[str, Any]]:
    """The `GET /costs` body: one row per project of the owner, one grouped query."""
    spent = (
        select(LLMCall.project_id.label("pid"), func.sum(LLMCall.cost_usd).label("total"))
        .group_by(LLMCall.project_id)
        .subquery()
    )
    rows = session.execute(
        select(Project.id, Project.name, Project.budget_usd, Project.status, spent.c.total)
        .outerjoin(spent, spent.c.pid == Project.id)
        .where(Project.owner_id == owner_id)
        .order_by(Project.created_at)
    ).all()
    return [
        {
            "project_id": str(pid),
            "name": name,
            "spent_usd": money(total),
            "budget_usd": money(budget) if budget is not None else None,
            "status": status,
        }
        for pid, name, budget, status, total in rows
    ]
