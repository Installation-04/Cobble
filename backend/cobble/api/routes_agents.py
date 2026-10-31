"""Agents API (ADR 0007): logs, diff and the pause/resume/stop/retry controls of a task.

The agent runner and the git provider come from `app.state.agents` / `app.state.git` when set
(tests, the fake pack mode); otherwise they are built once from the pack settings, and are
`None` when the pack is not configured. Without them logs fall back to the stored log tail,
the diff answers 503 and stopping a live run answers 503 (nothing changes).
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Query, Request, Response
from sqlalchemy import select

from cobble.capabilities.agent import AgentRunner, AgentRunNotFound, AgentUnavailable
from cobble.capabilities.git import GitProvider, RepoRef, cap_diff
from cobble.db import Task, TaskRun
from cobble.scheduler import control

from .deps import AppSettings, Db, OwnedProject, RedisDep
from .errors import ApiError
from .schemas import TaskOut

log = logging.getLogger(__name__)
router = APIRouter()

_UNSET = object()


def _pack(request: Request) -> Any:
    """The pack's collaborators, built on first use (never raises, `None` when absent)."""
    state = request.app.state
    cached = getattr(state, "pack_services", _UNSET)
    if cached is _UNSET:
        try:
            from cobble.providers.agent_service import build_pack_services

            cached = build_pack_services(state.settings)
        except Exception:
            log.warning("could not build the pack services for the API", exc_info=True)
            cached = None
        state.pack_services = cached
    return cached


def agent_runner(request: Request) -> AgentRunner | None:
    explicit = getattr(request.app.state, "agents", None)
    if explicit is not None:
        runner: AgentRunner = explicit
        return runner
    pack = _pack(request)
    return pack.agents if pack is not None else None


def git_provider(request: Request) -> GitProvider | None:
    explicit = getattr(request.app.state, "git", None)
    if explicit is not None:
        git: GitProvider = explicit
        return git
    pack = _pack(request)
    return pack.git if pack is not None else None


def _task(db: Db, project: OwnedProject, ref: str) -> Task:
    task = db.scalars(select(Task).where(Task.project_id == project.id, Task.ref == ref)).first()
    if task is None:
        raise ApiError(404, "not_found")
    return task


# --- logs ---------------------------------------------------------------------------------


@router.get("/projects/{project_id}/tasks/{ref}/logs")
def task_logs(
    ref: str,
    project: OwnedProject,
    db: Db,
    request: Request,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Response:
    task = _task(db, project, ref)
    run = db.scalars(
        select(TaskRun).where(TaskRun.task_id == task.id).order_by(TaskRun.started_at.desc())
    ).first()
    text, next_offset = "", offset
    if run is not None:
        runner = agent_runner(request)
        live = False
        if runner is not None and run.agent_run_id is not None:
            try:
                text, next_offset = runner.logs(run.agent_run_id, offset)
                live = True
            except (AgentRunNotFound, AgentUnavailable):
                pass
            except Exception:
                log.warning("reading the log of %s failed", task.ref, exc_info=True)
        if not live:
            tail = run.log_tail or ""
            text, next_offset = tail[offset:], max(offset, len(tail))
    return Response(
        text,
        media_type="text/plain",
        headers={"X-Next-Offset": str(next_offset), "Cache-Control": "no-store"},
    )


# --- diff ---------------------------------------------------------------------------------


@router.get("/projects/{project_id}/tasks/{ref}/diff")
def task_diff(
    ref: str, project: OwnedProject, db: Db, request: Request, settings: AppSettings
) -> dict[str, Any]:
    task = _task(db, project, ref)
    if task.branch is None or project.repo_name is None or project.repo_clone_url is None:
        return {"diff": "", "truncated": False}  # nothing was pushed yet
    git = git_provider(request)
    if git is None:
        raise ApiError(503, "git_unavailable")
    try:
        text, truncated = git.diff(
            RepoRef(project.repo_name, project.repo_clone_url),
            settings.base_branch,
            task.branch,
            request_number=task.pr_number,
        )
    except Exception:
        log.warning("could not read the diff of %s", task.ref, exc_info=True)
        raise ApiError(503, "git_unavailable") from None
    text, cut = cap_diff(text)
    return {"diff": text, "truncated": truncated or cut}


# --- controls -----------------------------------------------------------------------------


def _control(
    action: control.Action,
    ref: str,
    project: OwnedProject,
    db: Db,
    request: Request,
    redis: RedisDep,
) -> Task:
    task = _task(db, project, ref)
    try:
        control.apply(db, task, action, agents=agent_runner(request), redis=redis)
    except control.WrongState as exc:
        raise ApiError(409, "wrong_state", state=exc.state) from None
    except AgentUnavailable:
        db.rollback()
        raise ApiError(503, "agent_unavailable") from None
    db.refresh(task)
    return task


def _register(action: control.Action) -> None:
    def endpoint(
        ref: str, project: OwnedProject, db: Db, request: Request, redis: RedisDep
    ) -> TaskOut:
        return TaskOut.model_validate(_control(action, ref, project, db, request, redis))

    endpoint.__name__ = f"task_{action.value}"
    router.add_api_route(
        f"/projects/{{project_id}}/tasks/{{ref}}/{action.value}",
        endpoint,
        methods=["POST"],
        response_model=TaskOut,
    )


for _action in control.Action:
    _register(_action)
