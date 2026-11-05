"""Owner settings of the cost router (ADR 0021): electricity of local models and the per-task
cap. Administrators only. Electricity is an estimate, never a measure."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from cobble.router import cost_settings, task_budget
from cobble.router.cost_settings import (
    MAX_MULTIPLIER,
    MAX_PRICE_KWH_USD,
    MAX_WATTS,
    CostSettings,
)

from .deps import AdminUser, AppSettings, Db

router = APIRouter()


class CostSettingsBody(BaseModel):
    # Unset (null) or 0: no electricity cost (today's behaviour).
    electricity_price_kwh_usd: Decimal | None = Field(default=None, ge=0, le=MAX_PRICE_KWH_USD)
    electricity_watts: int | None = Field(default=None, ge=0, le=MAX_WATTS)
    electricity_counts_in_budget: bool = False
    # null: the configured default; 0: no per-task cap.
    task_budget_multiplier: Decimal | None = Field(default=None, ge=0, le=MAX_MULTIPLIER)


def _text(value: Decimal | None) -> str | None:
    return format(value.normalize(), "f") if value is not None else None


def _view(values: CostSettings, settings: Any) -> dict[str, Any]:
    return {
        "electricity_price_kwh_usd": _text(values.electricity_price_kwh_usd),
        "electricity_watts": values.electricity_watts,
        "electricity_counts_in_budget": values.electricity_counts_in_budget,
        "electricity_enabled": values.electricity_enabled,
        "task_budget_multiplier": _text(values.task_budget_multiplier),
        "effective_task_budget_multiplier": _text(task_budget.multiplier(values, settings)),
        "task_budget_floor_usd": _text(settings.task_budget_floor_usd),
    }


@router.get("/settings/costs")
def get_cost_settings(_admin: AdminUser, db: Db, settings: AppSettings) -> dict[str, Any]:
    return _view(cost_settings.read(db), settings)


@router.put("/settings/costs")
def put_cost_settings(
    body: CostSettingsBody, _admin: AdminUser, db: Db, settings: AppSettings
) -> dict[str, Any]:
    values = CostSettings(
        electricity_price_kwh_usd=body.electricity_price_kwh_usd,
        electricity_watts=body.electricity_watts,
        electricity_counts_in_budget=body.electricity_counts_in_budget,
        task_budget_multiplier=body.task_budget_multiplier,
    )
    cost_settings.write(db, values)
    return _view(values, settings)
