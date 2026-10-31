"""Build endpoints: start the project, list its tasks (ADR 0006). Scoped to the owner.

`POST /projects/{id}/start` only checks the phase and queues a `start` job: creating the
repository pushes the template to the git server, which is too slow for a request. The worker
runs the job (`Scheduler.run_start_job`), then the scheduler loop takes over.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from redis.exceptions import RedisError
from sqlalchemy import select

from cobble.db import Task, TaskRun
from cobble.events import enqueue_job
from cobble.scheduler.rules import ref_key

from .deps import Db, OwnedProject, RedisDep
from .errors import ApiError
from .schemas import TaskDetailOut, TaskOut

router = APIRouter()


@router.post("/projects/{project_id}/start", status_code=202)
def start_project(project: OwnedProject, redis: RedisDep) -> dict[str, Any]:
    if project.phase != "ready":
        raise ApiError(409, "wrong_phase", phase=project.phase)
    if project.status != "active":
        raise ApiError(409, "project_paused")
    try:
        enqueue_job(redis, "start", project.id)
    except RedisError:
        raise ApiError(503, "queue_unavailable") from None
    return {}


@router.get("/projects/{project_id}/tasks", response_model=list[TaskOut])
def list_tasks(project: OwnedProject, db: Db) -> list[Task]:
    tasks = db.scalars(select(Task).where(Task.project_id == project.id))
    return sorted(tasks, key=lambda t: ref_key(t.ref))


@router.get("/projects/{project_id}/tasks/{ref}", response_model=TaskDetailOut)
def get_task(ref: str, project: OwnedProject, db: Db) -> dict[str, Any]:
    task = db.scalars(select(Task).where(Task.project_id == project.id, Task.ref == ref)).first()
    if task is None:
        raise ApiError(404, "not_found")
    runs = db.scalars(
        select(TaskRun).where(TaskRun.task_id == task.id).order_by(TaskRun.started_at)
    )
    return {**TaskOut.model_validate(task).model_dump(), "runs": list(runs)}
