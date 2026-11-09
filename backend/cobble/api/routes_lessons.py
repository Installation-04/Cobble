"""Lessons learned of a project (ADR 0026): list, add, edit, disable and delete.

Plain text only: the front end shows it as text, never as markup.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Response
from pydantic import BaseModel, ConfigDict, StringConstraints
from sqlalchemy import select

from cobble.db import ProjectLesson
from cobble.scheduler import lessons

from .deps import Db, OwnedProject, parse_id
from .errors import ApiError

router = APIRouter()

LessonText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=lessons.MAX_TEXT)
]


class LessonOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    text: str
    source: str
    task_ref: str | None
    active: bool
    hits: int
    created_at: datetime
    injected: bool = False  # shown to the next agent of the project


class LessonIn(BaseModel):
    text: LessonText


class LessonPatch(BaseModel):
    text: LessonText | None = None
    active: bool | None = None


def _all(db: Db, project_id: uuid.UUID) -> list[ProjectLesson]:
    stmt = (
        select(ProjectLesson)
        .where(ProjectLesson.project_id == project_id)
        .order_by(ProjectLesson.created_at.desc(), ProjectLesson.id)
    )
    return list(db.scalars(stmt))


def _out(db: Db, project_id: uuid.UUID, rows: list[ProjectLesson]) -> list[LessonOut]:
    shown = {row.id for row in lessons.injected(db, project_id)}
    return [
        LessonOut.model_validate(r).model_copy(update={"injected": r.id in shown}) for r in rows
    ]


def _one(db: Db, project_id: uuid.UUID, lesson_id: str) -> ProjectLesson:
    row = db.get(ProjectLesson, parse_id(lesson_id))
    if row is None or row.project_id != project_id:
        raise ApiError(404, "not_found")
    return row


@router.get("/projects/{project_id}/lessons", response_model=list[LessonOut])
def list_lessons(project: OwnedProject, db: Db) -> list[LessonOut]:
    return _out(db, project.id, _all(db, project.id))


@router.post("/projects/{project_id}/lessons", status_code=201, response_model=LessonOut)
def add_lesson(body: LessonIn, project: OwnedProject, db: Db) -> LessonOut:
    row = lessons.record(db, project.id, body.text, lessons.MANUAL)
    if row is None:
        db.rollback()
        raise ApiError(409, "lessons_full", max=lessons.MAX_ACTIVE)
    if not row.active:  # a lesson the owner disabled earlier: adding it again turns it back on
        row.active = True
    db.commit()
    return _out(db, project.id, [row])[0]


@router.patch("/projects/{project_id}/lessons/{lesson_id}", response_model=LessonOut)
def edit_lesson(lesson_id: str, body: LessonPatch, project: OwnedProject, db: Db) -> LessonOut:
    row = _one(db, project.id, lesson_id)
    if body.text is not None:
        row.text = lessons.clip(lessons.redact(body.text))
        if not row.text:
            raise ApiError(422, "validation_error", fields=["text"])
    if body.active is not None:
        if (
            body.active
            and not row.active
            and lessons.active_count(db, project.id) >= lessons.MAX_ACTIVE
        ):
            raise ApiError(409, "lessons_full", max=lessons.MAX_ACTIVE)
        row.active = body.active
    db.commit()
    return _out(db, project.id, [row])[0]


@router.delete("/projects/{project_id}/lessons/{lesson_id}", status_code=204)
def delete_lesson(lesson_id: str, project: OwnedProject, db: Db) -> Response:
    row = _one(db, project.id, lesson_id)
    db.delete(row)
    db.commit()
    return Response(status_code=204)
