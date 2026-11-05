"""Per-task cost cap (ADR 0021).

A task may spend `multiplier` times its own estimate, never less than a small floor (so a free
or tiny estimate does not stop a task that costs a few cents). The estimate of a task comes from
the approved plan (`size_cost_usd` by size, stored with the plan); a plan stored before that
existed falls back to the flat settings. The cap is checked before each call: a call already in
flight when the cap is crossed still completes, so a task can overshoot by that one call.
"""

from __future__ import annotations

import uuid
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cobble.config import Settings
from cobble.db import LLMCall, Plan, Task

from .cost_settings import CostSettings


def plan_estimate_doc(session: Session, project_id: uuid.UUID) -> dict[str, object] | None:
    """The estimate stored with the approved plan (the latest version), else the latest plan."""
    plans = session.execute(
        select(Plan.estimate, Plan.status)
        .where(Plan.project_id == project_id)
        .order_by(Plan.version.desc())
    ).all()
    for wanted in ("approved", None):
        for estimate, status in plans:
            if isinstance(estimate, dict) and (wanted is None or status == wanted):
                return estimate
    return None


def _decimal(value: object) -> Decimal | None:
    try:
        parsed = Decimal(str(value))
    except InvalidOperation:
        return None
    return parsed if parsed.is_finite() and parsed >= 0 else None


def size_estimate(estimate: dict[str, object] | None, size: str, settings: Settings) -> Decimal:
    """What a task of `size` is expected to cost, in USD."""
    by_size = estimate.get("size_cost_usd") if estimate else None
    if isinstance(by_size, dict):
        found = _decimal(by_size.get(size))
        if found is not None:
            return found
    tokens = {"S": settings.estimate_tokens_s, "M": settings.estimate_tokens_m}.get(
        size, settings.estimate_tokens_m
    )
    return Decimal(tokens * 3 // 2) / 1000 * settings.estimate_usd_per_1k_tokens


def multiplier(values: CostSettings, settings: Settings) -> Decimal:
    chosen = values.task_budget_multiplier
    return chosen if chosen is not None else settings.task_budget_multiplier


def cap_for(
    estimate: dict[str, object] | None, size: str, values: CostSettings, settings: Settings
) -> Decimal | None:
    """The cap of a task of `size` in USD, or None when the owner turned the cap off (0)."""
    factor = multiplier(values, settings)
    if factor <= 0:
        return None
    return max(settings.task_budget_floor_usd, size_estimate(estimate, size, settings) * factor)


def task_spent(session: Session, task_id: uuid.UUID, *, with_electricity: bool) -> Decimal:
    column: Any = LLMCall.cost_usd
    if with_electricity:
        column = column + func.coalesce(LLMCall.electricity_usd, 0)
    total = session.scalar(
        select(func.coalesce(func.sum(column), 0)).where(LLMCall.task_id == task_id)
    )
    return Decimal(str(total or 0))


def task_facts(session: Session, task_id: uuid.UUID) -> tuple[uuid.UUID, str, str] | None:
    """(project id, ref, size) of a task, or None when it is unknown."""
    row = session.execute(
        select(Task.project_id, Task.ref, Task.size).where(Task.id == task_id)
    ).first()
    return (row[0], row[1], row[2]) if row else None
