"""Costs API (ADR 0007): what the LLM calls cost, per project and across projects."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from cobble import costs

from .deps import CurrentUser, Db, OwnedProject

router = APIRouter()


@router.get("/projects/{project_id}/costs")
def project_costs(project: OwnedProject, db: Db) -> dict[str, Any]:
    return costs.project_costs(db, project)


@router.get("/costs")
def all_costs(user: CurrentUser, db: Db) -> list[dict[str, Any]]:
    return costs.global_costs(db, user.id)
