"""Cost estimate stored with a plan and shown before launch.

Tokens per task: `S` and `M` base values, multiplied by 1.5 for the test-writer and reviewer
passes. Cost is tokens / 1000 x the configured price, rounded to cents.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from cobble.config import Settings

from .plan_schema import Plan

CENT = Decimal("0.01")


def _cost(tokens: int, usd_per_1k: Decimal) -> str:
    return str((Decimal(tokens) / 1000 * usd_per_1k).quantize(CENT, rounding=ROUND_HALF_UP))


def estimate_plan(
    plan: Plan, *, tokens_s: int, tokens_m: int, usd_per_1k_tokens: Decimal
) -> dict[str, Any]:
    """Return `{tokens, cost_usd, milestones: [{id, tokens, cost_usd}]}` (costs are strings)."""
    per_size = {"S": tokens_s * 3 // 2, "M": tokens_m * 3 // 2}
    by_milestone = {m.id: 0 for m in plan.milestones}
    for task in plan.tasks:
        by_milestone[task.milestone] = by_milestone.get(task.milestone, 0) + per_size[task.size]
    total = sum(by_milestone.values())
    return {
        "tokens": total,
        "cost_usd": _cost(total, usd_per_1k_tokens),
        "milestones": [
            {"id": mid, "tokens": tokens, "cost_usd": _cost(tokens, usd_per_1k_tokens)}
            for mid, tokens in by_milestone.items()
        ],
    }


def estimate_from_settings(plan: Plan, settings: Settings) -> dict[str, Any]:
    return estimate_plan(
        plan,
        tokens_s=settings.estimate_tokens_s,
        tokens_m=settings.estimate_tokens_m,
        usd_per_1k_tokens=settings.estimate_usd_per_1k_tokens,
    )
