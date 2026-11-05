"""Cost estimate stored with a plan and shown before launch.

Tokens per task: `S` and `M` base values, multiplied by 1.5 for the test-writer and reviewer
passes. Cost is tokens / 1000 x a price, rounded to cents.

The price is the flat configured one, unless the caller knows the model each role will use
(ADR 0021): then the worker's tokens are priced at the worker chain's first model, and the
test-writer and reviewer passes (a quarter of the base each) at theirs, so the estimate matches
what the router will actually charge. A free or local model costs 0; a role whose model has no
known price falls back to the flat price. Electricity is not part of the estimate.
"""

from __future__ import annotations

from collections.abc import Callable
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from cobble.capabilities.llm import Role
from cobble.config import Settings

from .plan_schema import Plan

CENT = Decimal("0.01")
MICRO = Decimal("0.000001")

# Share of the base tokens each role handles; the three add up to the 1.5 multiplier.
ROLE_SHARE: dict[Role, Decimal] = {
    Role.WORKER: Decimal("1"),
    Role.TEST_WRITER: Decimal("0.25"),
    Role.REVIEWER: Decimal("0.25"),
}
# Of the tokens of a call, the part that is the prompt (the rest is the answer).
PROMPT_SHARE = Decimal("0.75")

# USD per 1000 tokens of a role's first model; None when it has no known price.
RolePrice = Callable[[Role], Decimal | None]


def blended_per_1k(prompt_usd: Decimal, completion_usd: Decimal) -> Decimal:
    """USD per 1000 tokens from per-token prompt and completion prices."""
    return (prompt_usd * PROMPT_SHARE + completion_usd * (1 - PROMPT_SHARE)) * 1000


def _task_cost(base_tokens: int, flat: Decimal, role_price: RolePrice | None) -> Decimal:
    """Exact USD cost of a task whose base is `base_tokens` (before rounding)."""
    if role_price is None:
        return Decimal(base_tokens * 3 // 2) / 1000 * flat
    total = Decimal(0)
    for role, share in ROLE_SHARE.items():
        price = role_price(role)
        total += Decimal(base_tokens) * share / 1000 * (flat if price is None else price)
    return total


def estimate_plan(
    plan: Plan,
    *,
    tokens_s: int,
    tokens_m: int,
    usd_per_1k_tokens: Decimal,
    role_price: RolePrice | None = None,
) -> dict[str, Any]:
    """Return `{tokens, cost_usd, milestones: [{id, tokens, cost_usd}], size_cost_usd}`
    (costs are strings). `size_cost_usd` is the expected cost of one task of each size, which
    the per-task cap is derived from."""
    base = {"S": tokens_s, "M": tokens_m}
    per_size = {size: tokens * 3 // 2 for size, tokens in base.items()}
    cost_by_size = {
        size: _task_cost(tokens, usd_per_1k_tokens, role_price) for size, tokens in base.items()
    }
    by_milestone = {m.id: 0 for m in plan.milestones}
    cost_by_milestone = {m.id: Decimal(0) for m in plan.milestones}
    for task in plan.tasks:
        by_milestone[task.milestone] = by_milestone.get(task.milestone, 0) + per_size[task.size]
        cost_by_milestone[task.milestone] = (
            cost_by_milestone.get(task.milestone, Decimal(0)) + cost_by_size[task.size]
        )
    total = sum(by_milestone.values())
    total_cost = sum(cost_by_milestone.values(), Decimal(0))

    def cents(value: Decimal) -> str:
        return str(value.quantize(CENT, rounding=ROUND_HALF_UP))

    return {
        "tokens": total,
        "cost_usd": cents(total_cost),
        "milestones": [
            {"id": mid, "tokens": tokens, "cost_usd": cents(cost_by_milestone[mid])}
            for mid, tokens in by_milestone.items()
        ],
        "size_cost_usd": {
            size: str(cost.quantize(MICRO, rounding=ROUND_HALF_UP))
            for size, cost in cost_by_size.items()
        },
    }


def estimate_from_settings(
    plan: Plan, settings: Settings, role_price: RolePrice | None = None
) -> dict[str, Any]:
    return estimate_plan(
        plan,
        tokens_s=settings.estimate_tokens_s,
        tokens_m=settings.estimate_tokens_m,
        usd_per_1k_tokens=settings.estimate_usd_per_1k_tokens,
        role_price=role_price,
    )
