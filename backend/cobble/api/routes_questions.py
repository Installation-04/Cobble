"""Questions agents ask the user (ADR 0025). Scoped to the owner; unsafe methods need the CSRF
header like every other route.

`GET /projects/{id}/questions` lists them (open first), `POST .../{qid}/answer` and
`POST .../{qid}/skip` close one; the scheduler then resumes the task with the answer in the
next prompt of its agent.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import case, select

from cobble.db import Task, TaskQuestion
from cobble.scheduler import questions

from .deps import Db, OwnedProject, RedisDep, parse_id
from .errors import ApiError

router = APIRouter()


class QuestionOut(BaseModel):
    id: uuid.UUID
    task_id: str  # the task reference (T-003)
    task_title: str
    question: str
    choices: list[str]
    status: str
    answer: str | None
    created_at: datetime
    answered_at: datetime | None


class QuestionList(BaseModel):
    open: int
    items: list[QuestionOut]


class AnswerIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: Annotated[str, Field(min_length=1, max_length=questions.ANSWER_CHARS)]


def _out(row: TaskQuestion, task: Task) -> QuestionOut:
    return QuestionOut(
        id=row.id,
        task_id=task.ref,
        task_title=task.title,
        question=row.question,
        choices=list(row.choices),
        status=row.status,
        answer=row.answer,
        created_at=row.created_at,
        answered_at=row.answered_at,
    )


@router.get("/projects/{project_id}/questions", response_model=QuestionList)
def list_questions(project: OwnedProject, db: Db) -> QuestionList:
    rows = db.execute(
        select(TaskQuestion, Task)
        .join(Task, Task.id == TaskQuestion.task_id)
        .where(Task.project_id == project.id)
        .order_by(
            case((TaskQuestion.status == questions.OPEN, 0), else_=1),
            TaskQuestion.created_at.desc(),
        )
    ).all()
    items = [_out(q, t) for q, t in rows]
    return QuestionList(open=sum(1 for i in items if i.status == questions.OPEN), items=items)


def _close(
    project: OwnedProject, db: Db, redis: RedisDep, question_id: str, text: str | None
) -> dict[str, Any]:
    try:
        row = questions.answer(db, project.id, parse_id(question_id), text, redis=redis)
    except questions.QuestionError as exc:
        raise ApiError(exc.status, exc.code) from None
    task = db.get(Task, row.task_id)
    if task is None:
        raise ApiError(404, "not_found")
    return _out(row, task).model_dump(mode="json")


@router.post("/projects/{project_id}/questions/{question_id}/answer", response_model=QuestionOut)
def answer_question(
    question_id: str, body: AnswerIn, project: OwnedProject, db: Db, redis: RedisDep
) -> dict[str, Any]:
    return _close(project, db, redis, question_id, body.answer)


@router.post("/projects/{project_id}/questions/{question_id}/skip", response_model=QuestionOut)
def skip_question(
    question_id: str, project: OwnedProject, db: Db, redis: RedisDep
) -> dict[str, Any]:
    return _close(project, db, redis, question_id, None)
