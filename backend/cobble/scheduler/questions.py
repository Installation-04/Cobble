"""Questions an agent asks the user (ADR 0025).

An agent stops its run with a `question` outcome instead of guessing. The scheduler records it
here, the task waits as `waiting_human` (no run, no tokens, no attempt used), the user answers
or skips through the API, and the next run of the same kind starts with the answers in its
prompt. Everything in this module is additive to the scheduler: `engine.py` only calls
`record`, `has_open`, `addendum` and `close_open`.

Bounds: at most MAX_QUESTIONS per task (a further question is skipped by the system and the
agent is told to decide), QUESTION_CHARS / CHOICE_CHARS / ANSWER_CHARS of text, MAX_CHOICES
choices. Question and answer texts are never written to the logs.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from redis import Redis
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cobble.capabilities.agent import AgentQuestion
from cobble.db import Task, TaskQuestion, TaskRun
from cobble.events import publish_project

from . import rules

OPEN = "open"
ANSWERED = "answered"
SKIPPED = "skipped"
RUN_STATE = "question"  # TaskRun.state of the run that asked

MAX_QUESTIONS = 3
QUESTION_CHARS = 2000
CHOICE_CHARS = 200
ANSWER_CHARS = 2000
MAX_CHOICES = 6

OVER_LIMIT_LOG = "the agent asked a question although its questions for this task were used up"

ASK_HELP = (
    "\nIf you cannot go on without a decision only the user can take (a requirement that is "
    "unclear or contradictory, not a technical detail you can settle yourself), you may ask "
    "ONE question and stop: write the file .cobble/question.json containing "
    '{"question": "...", "choices": ["...", "..."]} ("choices" is optional), commit what is '
    "done, and end your work. Do not guess and do not ask about what the task already "
    "states. You may ask at most {left} more question(s) for this task.\n"
)


class QuestionError(Exception):
    """The answer is refused; `code` is the machine-readable reason (HTTP 409/422)."""

    def __init__(self, status: int, code: str) -> None:
        super().__init__(code)
        self.status = status
        self.code = code


def _now() -> datetime:
    return datetime.now(UTC)


def clean_text(text: str, limit: int) -> str:
    """Single bounded string without control characters (newlines are kept)."""
    kept = "".join(ch for ch in text if ch in "\n\t" or ch.isprintable())
    return kept.strip()[:limit]


def _questions(session: Session, task: Task) -> list[TaskQuestion]:
    return list(
        session.scalars(
            select(TaskQuestion)
            .where(TaskQuestion.task_id == task.id)
            .order_by(TaskQuestion.created_at, TaskQuestion.id)
        )
    )


def has_open(session: Session, task: Task) -> bool:
    return any(q.status == OPEN for q in _questions(session, task))


def left(session: Session, task: Task) -> int:
    used = session.scalar(
        select(func.count()).select_from(TaskQuestion).where(TaskQuestion.task_id == task.id)
    )
    return max(0, MAX_QUESTIONS - (used or 0))


def record(
    session: Session,
    task: Task,
    run: TaskRun,
    asked: AgentQuestion | None,
    emit: Callable[[uuid.UUID, str, dict[str, Any]], None],
) -> TaskQuestion | None:
    """Store the question of a `question` run. Returns the row when the user must answer.

    A question beyond the budget of the task (or an unreadable one) is stored as `skipped` and
    None is returned: the scheduler goes on at once, the agent is told to decide by itself.
    Idempotent per run: the same run never creates two rows."""
    existing = session.scalars(select(TaskQuestion).where(TaskQuestion.run_id == run.id)).first()
    if existing is not None:
        return existing if existing.status == OPEN else None
    text = clean_text(asked.text, QUESTION_CHARS) if asked is not None else ""
    choices = (
        [c for c in (clean_text(c, CHOICE_CHARS) for c in asked.choices[:MAX_CHOICES]) if c]
        if asked is not None
        else []
    )
    over = left(session, task) == 0 or not text
    row = TaskQuestion(
        task_id=task.id,
        run_id=run.id,
        question=text or "-",
        choices=choices,
        status=SKIPPED if over else OPEN,
        created_at=_now(),
        answered_at=_now() if over else None,
    )
    session.add(row)
    session.commit()
    if over:
        return None
    emit(
        task.project_id,
        "task.question",
        {
            "task_id": task.ref,
            "question_id": str(row.id),
            "question": row.question,
            "choices": row.choices,
        },
    )
    return row


def addendum(session: Session, task: Task) -> str:
    """The block appended to a run's instructions: earlier answers, then how to ask again."""
    rows = _questions(session, task)
    parts: list[str] = []
    done = [q for q in rows if q.status != OPEN]
    if done:
        lines = ["\nQuestions you asked earlier, and the user's decisions (follow them):"]
        for q in done:
            if q.status == ANSWERED and q.answer:
                lines.append(f"- Q: {q.question}\n  A: {q.answer}")
            else:
                lines.append(
                    f"- Q: {q.question}\n  A: (no answer: decide yourself, keep it simple and "
                    "write the assumption in a code comment)"
                )
        parts.append("\n".join(lines) + "\n")
    remaining = max(0, MAX_QUESTIONS - len(rows))
    if remaining:
        parts.append(ASK_HELP.replace("{left}", str(remaining)))
    else:
        parts.append("\nDo not ask the user anything more: decide yourself.\n")
    return "".join(parts)


def close_open(session: Session, task: Task) -> None:
    """Mark the open questions of a task skipped (the task was stopped or retried). No commit."""
    for q in _questions(session, task):
        if q.status == OPEN:
            q.status = SKIPPED
            q.answered_at = _now()


def open_count(session: Session, project_id: uuid.UUID) -> int:
    return (
        session.scalar(
            select(func.count())
            .select_from(TaskQuestion)
            .join(Task, Task.id == TaskQuestion.task_id)
            .where(Task.project_id == project_id, TaskQuestion.status == OPEN)
        )
        or 0
    )


def answer(
    session: Session,
    project_id: uuid.UUID,
    question_id: uuid.UUID,
    text: str | None,
    *,
    redis: Redis | None = None,
) -> TaskQuestion:
    """Answer (`text`) or skip (`text` is None) a question, and release its task.

    The task goes to `paused` (waiting for a slot): the scheduler starts the next run of the
    same kind with the answer in its prompt, without using up an attempt. Raises QuestionError.
    """
    row = session.get(TaskQuestion, question_id)
    task = session.get(Task, row.task_id) if row is not None else None
    if row is None or task is None or task.project_id != project_id:
        raise QuestionError(404, "not_found")
    if row.status != OPEN:
        raise QuestionError(409, "question_closed")
    if text is not None:
        text = clean_text(text, ANSWER_CHARS)
        if not text:
            raise QuestionError(422, "answer_empty")
        row.status, row.answer = ANSWERED, text
    else:
        row.status = SKIPPED
    row.answered_at = _now()
    previous = task.state
    if task.state == rules.WAITING_HUMAN and not has_other_open(session, task, row):
        task.state = rules.PAUSED
    session.commit()
    if redis is not None:
        publish_project(
            redis,
            task.project_id,
            "task.answered",
            {"task_id": task.ref, "question_id": str(row.id), "status": row.status},
        )
        if previous != task.state:
            publish_project(
                redis,
                task.project_id,
                "task.updated",
                {"task_id": task.ref, "state": task.state, "attempts": task.attempts},
            )
    return row


def has_other_open(session: Session, task: Task, row: TaskQuestion) -> bool:
    return any(q.status == OPEN and q.id != row.id for q in _questions(session, task))
