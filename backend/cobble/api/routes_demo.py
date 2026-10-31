"""Demo endpoints: milestones, validation, comments and reverts (ADR 0007). Owner-scoped.

Validating and commenting only touch the database. A revert needs git (restore the previous
tag), so the request is checked here and queued as a `revert` job that the worker runs.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, field_validator
from redis.exceptions import RedisError

from cobble.events import enqueue_job
from cobble.scheduler import demo
from cobble.scheduler.demo import DemoError

from .deps import Db, OwnedProject, RedisDep
from .errors import ApiError
from .schemas import TaskOut

router = APIRouter()


class MilestoneOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    ref: str
    title: str
    status: str
    tag: str | None
    preview_path: str | None
    # Extra to ADR 0007: building | running | failed while a preview exists, else null.
    preview_state: str | None
    built_at: datetime | None
    validated_at: datetime | None


class CommentIn(BaseModel):
    content: str

    @field_validator("content")
    @classmethod
    def _content(cls, value: str) -> str:
        value = value.strip()
        if not 1 <= len(value) <= 2000:
            raise ValueError("content must be 1-2000 characters")
        return value


class MilestoneAnswer(BaseModel):
    milestone: MilestoneOut


class TaskAnswer(BaseModel):
    task: TaskOut


def _raise(exc: DemoError) -> ApiError:
    return ApiError(exc.status, exc.code)


@router.get("/projects/{project_id}/milestones", response_model=list[MilestoneOut])
def list_milestones(project: OwnedProject, db: Db) -> list[Any]:
    return demo.milestones_of(db, project.id)


@router.post("/projects/{project_id}/milestones/{ref}/validate", response_model=MilestoneAnswer)
def validate_milestone(ref: str, project: OwnedProject, db: Db, redis: RedisDep) -> dict[str, Any]:
    try:
        milestone = demo.validate_milestone(db, demo.redis_emitter(redis), project, ref)
    except DemoError as exc:
        raise _raise(exc) from None
    return {"milestone": milestone}


@router.post(
    "/projects/{project_id}/milestones/{ref}/comments",
    status_code=201,
    response_model=TaskAnswer,
)
def comment_milestone(
    ref: str, body: CommentIn, project: OwnedProject, db: Db, redis: RedisDep
) -> dict[str, Any]:
    try:
        task = demo.add_comment(db, demo.redis_emitter(redis), project, ref, body.content)
    except DemoError as exc:
        raise _raise(exc) from None
    return {"task": task}


@router.post("/projects/{project_id}/milestones/{ref}/revert", status_code=202)
def revert_milestone(ref: str, project: OwnedProject, db: Db, redis: RedisDep) -> dict[str, Any]:
    try:
        demo.revert_target(db, project.id, ref)
    except DemoError as exc:
        raise _raise(exc) from None
    try:
        enqueue_job(redis, "revert", project.id, ref=ref)
    except RedisError:
        raise ApiError(503, "queue_unavailable") from None
    return {}
