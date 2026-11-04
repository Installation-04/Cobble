"""Mockup variants (ADR 0018): list, ask the planner for new ones, choose one.

Optional per project (`mockups_enabled`). Variants are plain text; this API never returns markup
the front end would have to interpret.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select

from cobble.db import MockupVariant, Spec
from cobble.events import publish_project
from cobble.orchestrator.mockups import MAX_VARIANTS, MIN_VARIANTS

from .deps import Db, OwnedProject, RedisDep
from .errors import ApiError
from .routes_planning import _enqueue, _latest_spec, _require_active, _require_phase

router = APIRouter()


class MockupOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    position: int
    title: str
    summary: str
    wireframe: str
    chosen: bool


class MockupsGenerateIn(BaseModel):
    feedback: str | None = Field(default=None, max_length=8000)
    count: int = Field(default=MAX_VARIANTS, ge=MIN_VARIANTS, le=MAX_VARIANTS)

    @field_validator("feedback")
    @classmethod
    def _feedback(cls, value: str | None) -> str | None:
        return (value or "").strip() or None


def _variants(db: Db, project_id: uuid.UUID) -> list[MockupVariant]:
    stmt = (
        select(MockupVariant)
        .where(MockupVariant.project_id == project_id)
        .order_by(MockupVariant.position)
    )
    return list(db.scalars(stmt))


@router.get("/projects/{project_id}/mockups", response_model=list[MockupOut])
def list_mockups(project: OwnedProject, db: Db) -> list[MockupVariant]:
    return _variants(db, project.id)


@router.post("/projects/{project_id}/mockups/generate", status_code=202)
def generate_mockups(
    project: OwnedProject, db: Db, redis: RedisDep, body: MockupsGenerateIn | None = None
) -> dict[str, Any]:
    if not project.mockups_enabled:
        raise ApiError(409, "mockups_disabled")
    _require_phase(project, "spec_review", "plan_review")
    spec: Spec | None = _latest_spec(db, project.id)
    if spec is None or spec.status != "approved":
        raise ApiError(409, "wrong_phase", phase=project.phase)
    _require_active(project)
    body = body or MockupsGenerateIn()
    _enqueue(redis, "mockups", project.id, feedback=body.feedback, count=body.count)
    return {}


@router.post("/projects/{project_id}/mockups/{variant_id}/choose", response_model=list[MockupOut])
def choose_mockup(
    variant_id: uuid.UUID, project: OwnedProject, db: Db, redis: RedisDep
) -> list[MockupVariant]:
    _require_phase(project, "spec_review", "plan_review")
    variants = _variants(db, project.id)
    if not any(v.id == variant_id for v in variants):
        raise ApiError(404, "not_found")
    for variant in variants:
        variant.chosen = variant.id == variant_id
    db.commit()
    publish_project(redis, project.id, "mockups.updated", {"count": len(variants)})
    return variants
