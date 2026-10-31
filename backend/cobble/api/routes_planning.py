"""Interview, spec and plan endpoints (ADR 0005). All are scoped to the project's owner."""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Header, Query, Request
from fastapi.responses import StreamingResponse
from redis.exceptions import RedisError
from sqlalchemy import select

from cobble.db import Message, Plan, Project, Spec
from cobble.events import enqueue_job, project_stream, publish_project
from cobble.orchestrator.service import message_payload

from .deps import Db, OwnedProject, RedisDep
from .errors import ApiError
from .schemas import (
    GenerateIn,
    MessageAccepted,
    MessageIn,
    MessageOut,
    PlanOut,
    SpecOut,
)
from .sse import SSE_HEADERS, SseOptions, event_stream, start_id

router = APIRouter()


def _require_phase(project: Project, *phases: str) -> None:
    if project.phase not in phases:
        raise ApiError(409, "wrong_phase", phase=project.phase)


def _require_active(project: Project) -> None:
    if project.status != "active":
        raise ApiError(409, "project_paused")


def _enqueue(redis: Any, kind: str, project_id: uuid.UUID, **extra: Any) -> None:
    try:
        enqueue_job(redis, kind, project_id, **extra)
    except RedisError:
        raise ApiError(503, "queue_unavailable") from None


def _latest_spec(db: Db, project_id: uuid.UUID) -> Spec | None:
    return db.scalars(
        select(Spec).where(Spec.project_id == project_id).order_by(Spec.version.desc()).limit(1)
    ).first()


def _latest_plan(db: Db, project_id: uuid.UUID) -> Plan | None:
    return db.scalars(
        select(Plan).where(Plan.project_id == project_id).order_by(Plan.version.desc()).limit(1)
    ).first()


# --- interview ------------------------------------------------------------------------------


@router.get("/projects/{project_id}/messages", response_model=list[MessageOut])
def list_messages(project: OwnedProject, db: Db) -> list[Message]:
    stmt = (
        select(Message)
        .where(Message.project_id == project.id)
        .order_by(Message.created_at, Message.id)
    )
    return list(db.scalars(stmt))


@router.post("/projects/{project_id}/messages", status_code=202, response_model=MessageAccepted)
def post_message(
    body: MessageIn, project: OwnedProject, db: Db, redis: RedisDep
) -> dict[str, Message]:
    _require_phase(project, "interview")
    _require_active(project)
    message = Message(project_id=project.id, role="user", content=body.content)
    db.add(message)
    db.commit()
    db.refresh(message)
    publish_project(redis, project.id, "message.created", {"message": message_payload(message)})
    _enqueue(redis, "reply", project.id, message_id=str(message.id))
    return {"message": message}


# --- spec -----------------------------------------------------------------------------------


@router.post("/projects/{project_id}/spec/generate", status_code=202)
def generate_spec(
    project: OwnedProject, redis: RedisDep, body: GenerateIn | None = None
) -> dict[str, Any]:
    _require_phase(project, "interview", "spec_review")
    _require_active(project)
    _enqueue(redis, "spec", project.id, feedback=body.feedback if body else None)
    return {}


@router.get("/projects/{project_id}/spec", response_model=SpecOut)
def get_spec(project: OwnedProject, db: Db) -> Spec:
    spec = _latest_spec(db, project.id)
    if spec is None:
        raise ApiError(404, "not_found")
    return spec


@router.post("/projects/{project_id}/spec/approve", response_model=SpecOut)
def approve_spec(project: OwnedProject, db: Db, redis: RedisDep) -> Spec:
    spec = _latest_spec(db, project.id)
    if spec is None:
        raise ApiError(404, "not_found")
    _require_phase(project, "spec_review")
    if spec.status != "approved":
        spec.status = "approved"
        db.commit()
        publish_project(redis, project.id, "spec.updated", {"version": spec.version})
    return spec


# --- plan -----------------------------------------------------------------------------------


@router.post("/projects/{project_id}/plan/generate", status_code=202)
def generate_plan(
    project: OwnedProject, db: Db, redis: RedisDep, body: GenerateIn | None = None
) -> dict[str, Any]:
    _require_phase(project, "spec_review", "plan_review")
    spec = _latest_spec(db, project.id)
    if spec is None or spec.status != "approved":
        raise ApiError(409, "wrong_phase", phase=project.phase)
    _require_active(project)
    _enqueue(redis, "plan", project.id, feedback=body.feedback if body else None)
    return {}


@router.get("/projects/{project_id}/plan", response_model=PlanOut)
def get_plan(project: OwnedProject, db: Db) -> Plan:
    plan = _latest_plan(db, project.id)
    if plan is None:
        raise ApiError(404, "not_found")
    return plan


@router.post("/projects/{project_id}/plan/approve", response_model=PlanOut)
def approve_plan(project: OwnedProject, db: Db, redis: RedisDep) -> Plan:
    plan = _latest_plan(db, project.id)
    if plan is None:
        raise ApiError(404, "not_found")
    _require_phase(project, "plan_review")
    plan.status = "approved"
    project.phase = "ready"
    db.commit()
    publish_project(redis, project.id, "plan.updated", {"version": plan.version})
    publish_project(redis, project.id, "phase.changed", {"phase": "ready"})
    return plan


# --- events ---------------------------------------------------------------------------------


@router.get("/projects/{project_id}/stream")
async def stream_events(
    request: Request,
    project: OwnedProject,
    db: Db,
    redis: RedisDep,
    last_event_id: Annotated[str | None, Header()] = None,
    last_event_id_query: Annotated[str | None, Query(alias="last_event_id")] = None,
) -> StreamingResponse:
    db.close()  # do not hold a connection for the whole life of the stream
    stream = project_stream(project.id)
    try:
        first = start_id(redis, stream, last_event_id, last_event_id_query)
    except RedisError:
        raise ApiError(503, "queue_unavailable") from None
    options: SseOptions = getattr(request.app.state, "sse", None) or SseOptions()
    return StreamingResponse(
        event_stream(redis, stream, first, request.is_disconnected, options),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )
