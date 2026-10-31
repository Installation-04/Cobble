"""The scheduler: drives tasks from `todo` to `merged` (ADR 0006).

All state lives in the database (`tasks`, `task_runs`), so the scheduler can be killed at any
moment and rebuilt: `reconcile()` re-attaches the runs that were in flight and the next `tick()`
carries on. `tick()` never blocks: it advances every task of every `building` project by at
most one step and returns.

Per task:  todo -> writing_tests (test-writer run) -> implementing (worker run) -> ci (merge
request open) -> merged.  A red CI, a failed, timed-out or looping run starts another worker
attempt carrying the failure log; after `escalate_after` failed attempts the worker runs on the
escalation model; after `max_attempts` the task is `failed` and its dependents `blocked`.
`paused` means "needs a new run but cannot start it now" (project budget reached, or no free
slot); `stopped` is a run that ended on request.
"""

from __future__ import annotations

import logging
import re
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from redis import Redis
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from cobble.auth import runtoken
from cobble.capabilities.agent import (
    AgentLimits,
    AgentOutcome,
    AgentRejected,
    AgentResult,
    AgentRunner,
    AgentRunNotFound,
    AgentTask,
    AgentUnavailable,
)
from cobble.capabilities.ci import CIProvider, CIState
from cobble.capabilities.git import (
    GitProvider,
    MergeRefused,
    MergeRequestRef,
    RepoRef,
    TagExists,
)
from cobble.capabilities.llm import Role
from cobble.capabilities.preview import (
    PreviewProvider,
    PreviewRejected,
    PreviewRequest,
    PreviewState,
    PreviewUnavailable,
)
from cobble.config import Settings
from cobble.db import Milestone, Project, Task, TaskRun
from cobble.events import publish_project

from . import control, demo, prompts, rules
from .materialize import NoApprovedPlan, materialize_tasks

log = logging.getLogger(__name__)

# Run states.
PENDING = "pending"  # row written, agent-service not called yet (or the answer was lost)
RUNNING = "running"
REJECTED = "rejected"  # the agent finished but CI (or the merge) said no
LOST = "lost"  # interrupted before the agent-service run id was recorded
ACTIVE_RUNS = (PENDING, RUNNING)
# Run states that use up one attempt.
COUNTED = (
    AgentOutcome.DONE.value,
    AgentOutcome.FAILED.value,
    AgentOutcome.TIMEOUT.value,
    AgentOutcome.LOOP_DETECTED.value,
    REJECTED,
)
LOG_TAIL_CHARS = 4000
RUN_TOKEN_SLACK_S = 60


class StartError(Exception):
    """`start_project` failed; `code` is the machine-readable reason."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class ReconcileReport:
    lost: int  # runs whose start was never recorded (not counted as an attempt)
    reattached: int  # runs found `running` and polled again
    open_merge_requests: int  # tasks waiting on CI that are checked again


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _now() -> datetime:
    return datetime.now(UTC)


def slug(name: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return text[:40].strip("-") or "project"


class Scheduler:
    def __init__(
        self,
        sessions: sessionmaker[Session],
        git: GitProvider,
        ci: CIProvider,
        agents: AgentRunner,
        settings: Settings,
        *,
        redis: Redis | None = None,
        model_for: Callable[[Role], str] | None = None,
        clock: Callable[[], datetime] = _now,
        preview: PreviewProvider | None = None,
    ) -> None:
        self._sessions = sessions
        self._git = git
        self._ci = ci
        self._agents = agents
        self._settings = settings
        self._redis = redis
        self._model_for = model_for or self._default_model_for
        self._clock = clock
        # Without a preview provider the demo flow is off: the project is `done` as soon as every
        # task is merged (the behaviour of ADR 0006).
        self._preview = preview

    # --- helpers --------------------------------------------------------------------------

    def _default_model_for(self, role: Role) -> str:
        return self._settings.role_models.get(role.value, self._settings.default_model)

    def _emit(self, project_id: uuid.UUID, event: str, payload: dict[str, Any]) -> None:
        if self._redis is not None:
            publish_project(self._redis, project_id, event, payload)

    def _emit_task(self, task: Task) -> None:
        self._emit(
            task.project_id,
            "task.updated",
            {"task_id": task.ref, "state": task.state, "attempts": task.attempts},
        )

    def _set_state(self, session: Session, task: Task, state: str) -> None:
        changed = task.state != state
        task.state = state
        session.commit()
        if changed:
            self._emit_task(task)

    def _runs(self, session: Session, task: Task) -> list[TaskRun]:
        return list(
            session.scalars(
                select(TaskRun).where(TaskRun.task_id == task.id).order_by(TaskRun.started_at)
            )
        )

    def _repo(self, project: Project) -> RepoRef:
        if project.repo_name is None or project.repo_clone_url is None:
            raise StartError("no_repository")
        return RepoRef(project.repo_name, project.repo_clone_url)

    def _views(self, session: Session, project_id: uuid.UUID) -> list[rules.TaskView]:
        return [
            rules.TaskView(
                t.ref,
                control.HELD if control.is_held(t.state, t.last_error) else t.state,
                tuple(t.depends_on),
                tuple(t.files),
            )
            for t in session.scalars(select(Task).where(Task.project_id == project_id))
        ]

    def _escalation_model(self) -> str:
        return self._settings.escalation_model or self._model_for(Role.PLANNER)

    # --- project lifecycle ----------------------------------------------------------------

    def start_project(self, project_id: uuid.UUID) -> bool:
        """`ready` -> `building`: repository from the template, CI on, tasks created.

        Idempotent: a project already `building` returns True, and a repository created by an
        earlier interrupted call is reused. Raises StartError.
        """
        with self._sessions() as session:
            project = session.get(Project, project_id)
            if project is None:
                raise StartError("not_found")
            if project.phase in ("building", "done"):
                return True
            if project.phase != "ready":
                raise StartError("wrong_phase")
            if project.repo_name is None:
                name = f"{slug(project.name)}-{project.id.hex[:6]}"
                try:
                    repo = self._git.create_repo_from_template(
                        name, Path(self._settings.template_dir)
                    )
                except Exception as exc:
                    log.warning("repository creation failed for %s", project_id, exc_info=True)
                    raise StartError("repo_error") from exc
                project.repo_name = repo.name
                project.repo_clone_url = repo.clone_url
                session.commit()  # remember the repository before anything else can fail
            if self._preview is not None:
                try:  # the state a revert of the first milestone goes back to (idempotent)
                    self._git.tag(
                        self._repo(project), demo.TEMPLATE_TAG, self._settings.base_branch
                    )
                except TagExists:
                    pass
                except Exception as exc:
                    log.warning("could not tag the template state of %s", project_id, exc_info=True)
                    raise StartError("repo_error") from exc
            try:
                self._ci.activate(self._repo(project))
                materialize_tasks(session, project_id, with_demo=self._preview is not None)
            except NoApprovedPlan as exc:
                session.rollback()
                raise StartError("no_plan") from exc
            except Exception as exc:
                session.rollback()
                log.warning("could not activate CI for %s", project_id, exc_info=True)
                raise StartError("ci_error") from exc
            project.phase = "building"
            session.commit()
            count = len(self._views(session, project_id))
        self._emit(project_id, "phase.changed", {"phase": "building"})
        self._emit(project_id, "project.building", {"tasks": count})
        return True

    def run_start_job(self, project_id: uuid.UUID) -> bool:
        """The `start` job: never raises; failures become a `job.failed` event."""
        self._emit(project_id, "job.started", {"kind": "start"})
        try:
            self.start_project(project_id)
        except StartError as exc:
            self._emit(project_id, "job.failed", {"kind": "start", "code": exc.code})
            return False
        except Exception:
            log.exception("unexpected error while starting %s", project_id)
            self._emit(project_id, "job.failed", {"kind": "start", "code": "internal_error"})
            return False
        return True

    # --- resumption -----------------------------------------------------------------------

    def reconcile(self) -> ReconcileReport:
        """Pick up after a restart. Safe to call at any time.

        - A run still `pending` (the process died around the call to the agent service, so its
          id was never recorded) is marked `lost`; it does not use up an attempt and the task
          gets a fresh run. The one risk is an orphan container, which its time limit ends.
        - Every run still `running` is polled again: finished runs are processed, runs the
          service no longer knows are marked failed, the others are simply watched on.
        - Tasks waiting on CI are checked again (merging an already merged request is a no-op).
        Nothing starts a second run for a task that already has an active one.
        """
        lost = 0
        reattached = 0
        waiting = 0
        with self._sessions() as session:
            for run in session.scalars(select(TaskRun).where(TaskRun.state == PENDING)):
                run.state = LOST
                run.finished_at = self._clock()
                run.log_tail = "interrupted before the agent run was recorded"
                lost += 1
            session.commit()
            reattached = (
                session.scalar(
                    select(func.count()).select_from(TaskRun).where(TaskRun.state == RUNNING)
                )
                or 0
            )
            waiting = (
                session.scalar(select(func.count()).select_from(Task).where(Task.state == rules.CI))
                or 0
            )
            project_ids = self._building_projects(session)
        for project_id in project_ids:
            self._advance_existing(project_id)
            self._advance_milestones(project_id)
        return ReconcileReport(lost, reattached, waiting)

    def run_forever(self, stop: threading.Event, interval_s: float | None = None) -> None:
        """The scheduler loop of the worker: reconcile once, then tick until stopped."""
        interval = self._settings.scheduler_interval_s if interval_s is None else interval_s
        try:
            self.reconcile()
        except Exception:
            log.exception("scheduler reconcile failed")
        while not stop.is_set():
            try:
                self.tick()
            except Exception:
                log.exception("scheduler tick failed")
            stop.wait(interval)

    # --- tick -----------------------------------------------------------------------------

    def _building_projects(self, session: Session) -> list[uuid.UUID]:
        return list(
            session.scalars(
                select(Project.id).where(Project.phase == "building").order_by(Project.created_at)
            )
        )

    def tick(self) -> None:
        """Advance every task of every building project by one step. Never blocks."""
        with self._sessions() as session:
            project_ids = self._building_projects(session)
        for project_id in project_ids:
            try:
                self._advance_existing(project_id)
                self._start_runnable(project_id)
                self._advance_milestones(project_id)
                self._check_done(project_id)
            except Exception:
                log.exception("scheduler step failed for project %s", project_id)

    def _advance_existing(self, project_id: uuid.UUID) -> None:
        with self._sessions() as session:
            tasks = list(
                session.scalars(
                    select(Task)
                    .where(
                        Task.project_id == project_id,
                        Task.state.in_([rules.WRITING_TESTS, rules.IMPLEMENTING, rules.CI]),
                    )
                    .order_by(Task.ref)
                )
            )
            ids = sorted(((t.ref, t.id) for t in tasks), key=lambda x: rules.ref_key(x[0]))
        for _ref, task_id in ids:
            try:
                self._step_task(project_id, task_id)
            except Exception:
                log.exception("scheduler step failed for task %s", task_id)
        self._propagate_blocked(project_id)

    def _step_task(self, project_id: uuid.UUID, task_id: uuid.UUID) -> None:
        with self._sessions() as session:
            project = session.get(Project, project_id)
            task = session.get(Task, task_id)
            if project is None or task is None:
                return
            if task.state in (rules.WRITING_TESTS, rules.IMPLEMENTING):
                self._step_run(session, project, task)
            elif task.state == rules.CI:
                self._step_ci(session, project, task)

    # --- agent runs -----------------------------------------------------------------------

    def _step_run(self, session: Session, project: Project, task: Task) -> None:
        runs = self._runs(session, task)
        last = runs[-1] if runs else None
        if last is not None and last.state in ACTIVE_RUNS:
            if last.state == PENDING or last.agent_run_id is None:
                return  # reconcile() decides what became of it
            try:
                result = self._agents.poll(last.agent_run_id)
            except AgentUnavailable:
                log.warning("agent service unreachable, run %s keeps going", last.agent_run_id)
                return
            except AgentRunNotFound:
                result = AgentResult(
                    AgentOutcome.FAILED, log="the agent service no longer knows this run"
                )
            if result is None:
                return
            self._finish_run(session, task, last, result)
        self._follow_up(session, project, task)

    def _finish_run(self, session: Session, task: Task, run: TaskRun, result: AgentResult) -> None:
        run.state = result.outcome.value
        run.iterations = result.iterations
        run.head_sha = result.head_sha
        run.finished_at = self._clock()
        run.log_tail = prompts.tail(result.log, LOG_TAIL_CHARS) if result.log else None
        if result.outcome is not AgentOutcome.DONE:
            detail = prompts.tail(result.log, LOG_TAIL_CHARS) if result.log else ""
            task.last_error = f"agent {result.outcome.value}: {detail}".rstrip(": ")
        session.commit()

    def _follow_up(self, session: Session, project: Project, task: Task) -> None:
        """Decide what comes after the last run of the task."""
        runs = self._runs(session, task)
        last = runs[-1] if runs else None
        if last is not None and last.state in ACTIVE_RUNS:
            return
        if last is None:
            # A demo task has no test-writer step (nothing to test first: it only seeds data).
            self._launch_or_hold(
                session, project, task, "worker" if task.kind == "demo" else "test-writer"
            )
        elif last.state == AgentOutcome.STOPPED.value:
            self._set_state(session, task, rules.STOPPED)
        elif last.state == AgentOutcome.BUDGET.value:
            self._set_state(session, task, rules.PAUSED)
        elif last.state == LOST:
            self._launch_or_hold(session, project, task, last.kind)
        elif last.kind == "test-writer":
            if last.state == AgentOutcome.DONE.value:
                self._launch_or_hold(session, project, task, "worker")
            else:
                self._launch_or_hold(session, project, task, "test-writer")
        elif last.state == AgentOutcome.DONE.value:
            self._open_merge_request(session, project, task)
        else:  # failed, timeout, loop_detected, rejected
            self._launch_or_hold(session, project, task, "worker")

    def _running_elsewhere(self, session: Session, task: Task) -> int:
        return (
            session.scalar(
                select(func.count())
                .select_from(Task)
                .where(
                    Task.project_id == task.project_id,
                    Task.state.in_(sorted(rules.RUNNING)),
                    Task.id != task.id,
                )
            )
            or 0
        )

    def _launch_or_hold(self, session: Session, project: Project, task: Task, kind: str) -> None:
        """Start the next run now, or park the task as `paused` (budget reached / no free slot)."""
        if task.kind == "revert":
            self._start_restore(session, project, task)
            return
        if (
            project.status != "active"
            or self._running_elsewhere(session, task) >= self._settings.max_parallel_agents
        ):
            self._set_state(session, task, rules.PAUSED)
            return
        self._launch(session, project, task, kind)

    def _launch(self, session: Session, project: Project, task: Task, kind: str) -> None:
        runs = self._runs(session, task)
        if any(r.state in ACTIVE_RUNS for r in runs):
            return  # never two runs for one task
        counted = sum(1 for r in runs if r.kind == kind and r.state in COUNTED)
        if counted >= self._settings.max_attempts:
            self._fail_task(session, task, task.last_error or f"{kind} failed {counted} times")
            return
        worker = kind == "worker"
        role = Role.WORKER if worker else Role.TEST_WRITER
        attempt = counted + 1 if worker else 1
        escalated = worker and counted >= self._settings.escalate_after
        model = self._escalation_model() if escalated else self._model_for(role)
        branch = task.branch or f"task/{task.ref.lower()}"
        view = prompts.PromptTask(
            task.ref,
            task.title,
            task.milestone,
            tuple(task.files),
            tuple(task.acceptance),
            task.tests,
            task.role,
            task.size,
        )
        if worker:
            make = prompts.demo_instructions if task.kind == "demo" else prompts.worker_instructions
            instructions = make(view, attempt, task.last_error)
        else:
            instructions = prompts.writer_instructions(view)
        limits = AgentLimits(
            max_iterations=self._settings.agent_max_iterations,
            max_seconds=self._settings.agent_max_seconds,
            cpu=self._settings.agent_cpu,
            memory_mb=self._settings.agent_memory_mb,
            pids=self._settings.agent_pids,
        )
        token = runtoken.issue(
            self._settings.run_token_secret,
            task_id=task.id,
            project_id=task.project_id,
            role=role.value,
            ttl_s=limits.max_seconds + RUN_TOKEN_SLACK_S,
            model_override=model if escalated else None,
        )
        agent_task = AgentTask(
            task_id=task.id,
            project_id=task.project_id,
            repo_clone_url=project.repo_clone_url or "",
            branch=branch,
            role=role,
            instructions=instructions,
            files=list(task.files),
            limits=limits,
            model=model,
            base_branch=self._settings.base_branch,
            # The test-writer writes tests that must fail until the worker has run: giving it the
            # test command would make the runner exit non-zero and look like a loop.
            test_command=prompts.local_test_command(task.tests) if worker else "",
            run_token=token,
            marker=prompts.marker(task.ref, role.value, attempt),
        )
        run = TaskRun(task_id=task.id, kind=kind, attempt=attempt, model=model, state=PENDING)
        session.add(run)
        session.commit()  # written before the call: a crash leaves a `pending` run to reconcile
        try:
            run_id = self._agents.start(agent_task)
        except AgentUnavailable:
            log.warning("agent service unreachable, %s will be started later", task.ref)
            session.delete(run)
            session.commit()
            return
        except AgentRejected as exc:
            run.state = AgentOutcome.FAILED.value
            run.finished_at = self._clock()
            run.log_tail = str(exc)[:LOG_TAIL_CHARS]
            task.last_error = f"agent service refused the run: {exc}"[:LOG_TAIL_CHARS]
            task.branch = branch
            task.state = rules.IMPLEMENTING if worker else rules.WRITING_TESTS
            session.commit()
            self._emit_task(task)
            return
        run.agent_run_id = run_id
        run.state = RUNNING
        task.branch = branch
        if worker:
            task.attempts = attempt
            task.escalated = task.escalated or escalated
        previous = task.state
        task.state = rules.IMPLEMENTING if worker else rules.WRITING_TESTS
        session.commit()
        if previous != task.state or worker:
            self._emit_task(task)

    def _fail_task(self, session: Session, task: Task, reason: str) -> None:
        task.last_error = reason[:LOG_TAIL_CHARS]
        self._set_state(session, task, rules.FAILED)

    # --- merge request and CI -------------------------------------------------------------

    def _last_worker_run(self, session: Session, task: Task) -> TaskRun | None:
        workers = [r for r in self._runs(session, task) if r.kind == "worker"]
        return workers[-1] if workers else None

    def _open_merge_request(self, session: Session, project: Project, task: Task) -> None:
        run = self._last_worker_run(session, task)
        if run is None or task.branch is None:
            return
        if task.pr_number is None:
            try:
                request = self._git.open_merge_request(
                    self._repo(project),
                    task.branch,
                    self._settings.base_branch,
                    f"{task.ref}: {task.title}",
                )
            except Exception:
                log.warning("could not open the merge request of %s", task.ref, exc_info=True)
                return  # retried on the next tick
            task.pr_number = request.number
        self._set_state(session, task, rules.CI)

    def _step_ci(self, session: Session, project: Project, task: Task) -> None:
        run = self._last_worker_run(session, task)
        if run is None or task.branch is None or task.pr_number is None:
            self._set_state(session, task, rules.IMPLEMENTING)
            return
        ref = run.head_sha or task.branch
        repo = self._repo(project)
        try:
            status = self._ci.status(repo, ref)
        except Exception:
            log.warning("could not read the CI status of %s", task.ref, exc_info=True)
            return
        if status.state is CIState.PENDING:
            started = _aware(run.finished_at or run.started_at)
            if (self._clock() - started).total_seconds() > self._settings.ci_timeout_s:
                self._reject(session, project, task, run, "CI did not finish in time")
            return
        if status.state is CIState.FAILURE:
            self._reject(session, project, task, run, status.detail or "CI failed")
            return
        request = MergeRequestRef(
            repo, task.pr_number, task.branch, self._settings.base_branch, run.head_sha
        )
        try:
            self._git.merge(request)
        except MergeRefused as exc:
            self._reject(session, project, task, run, f"merge refused: {exc}")
            return
        except Exception:
            log.warning("could not merge %s", task.ref, exc_info=True)
            return  # transient: retried on the next tick
        task.last_error = None
        self._set_state(session, task, rules.MERGED)

    def _reject(
        self, session: Session, project: Project, task: Task, run: TaskRun, detail: str
    ) -> None:
        """CI (or the merge) said no: this attempt failed, try again with the log."""
        run.state = REJECTED
        task.last_error = detail[:LOG_TAIL_CHARS]
        if task.kind == "revert":  # no agent can fix a restore: the operator decides
            self._set_state(session, task, rules.FAILED)
            return
        self._set_state(session, task, rules.IMPLEMENTING)
        self._launch_or_hold(session, project, task, "worker")

    # --- starting tasks, blocking, completion ---------------------------------------------

    @staticmethod
    def _next_kind(runs: list[TaskRun], task_kind: str = "plan") -> str | None:
        """The kind of run a task needs next, or None when it needs a merge request instead."""
        last = runs[-1] if runs else None
        if last is None:
            return "worker" if task_kind == "demo" else "test-writer"
        if last.kind == "test-writer":
            return "worker" if last.state == AgentOutcome.DONE.value else "test-writer"
        return None if last.state == AgentOutcome.DONE.value else "worker"

    def _start_runnable(self, project_id: uuid.UUID) -> None:
        with self._sessions() as session:
            project = session.get(Project, project_id)
            if project is None or project.status != "active":
                return  # budget reached: nothing new starts, running work continues
            refs = rules.runnable(
                self._views(session, project_id), self._settings.max_parallel_agents
            )
            by_ref = {
                t.ref: t.id
                for t in session.scalars(select(Task).where(Task.project_id == project_id))
            }
        for ref in refs:
            with self._sessions() as session:
                project = session.get(Project, project_id)
                task = session.get(Task, by_ref[ref])
                if project is None or task is None or task.state not in (rules.TODO, rules.PAUSED):
                    continue
                if task.kind == "revert":
                    self._start_restore(session, project, task)
                    continue
                kind = self._next_kind(self._runs(session, task), task.kind)
                if kind is None:
                    continue  # a finished worker waits for its merge request, not for a run
                self._launch(session, project, task, kind)

    def _propagate_blocked(self, project_id: uuid.UUID) -> None:
        with self._sessions() as session:
            refs = rules.blocked_refs(self._views(session, project_id))
            for ref in refs:
                task = session.scalars(
                    select(Task).where(Task.project_id == project_id, Task.ref == ref)
                ).one()
                task.last_error = "dependency_failed"
                self._set_state(session, task, rules.BLOCKED)

    def _check_done(self, project_id: uuid.UUID) -> None:
        with self._sessions() as session:
            project = session.get(Project, project_id)
            if project is None or project.phase != "building":
                return
            if self._preview is not None:  # demo flow: the user's validations finish the project
                demo.finish_if_validated(session, self._emit, project)
                return
            views = self._views(session, project_id)
            if not rules.all_merged(views):
                return
            project.phase = "done"
            session.commit()
            total = len(views)
        self._emit(project_id, "phase.changed", {"phase": "done"})
        self._emit(project_id, "project.done", {"tasks": total})

    # --- restore (revert of a milestone) --------------------------------------------------

    def _start_restore(self, session: Session, project: Project, task: Task) -> None:
        """Open the merge request that brings a tagged tree back; CI and merge go the usual way.

        The tag to restore is the first acceptance item (`restore:<tag>`). Idempotent: opening
        the same request twice returns it, so a crash right after this call is harmless.
        """
        tag = (task.acceptance[0] if task.acceptance else "").removeprefix(demo.RESTORE_PREFIX)
        try:
            request = self._git.restore_tag(self._repo(project), tag, task.title)
        except Exception:
            log.warning("could not restore %s for %s", tag, task.ref, exc_info=True)
            return  # retried on the next tick
        if request is None:  # the default branch already has that tree
            task.last_error = None
            self._set_state(session, task, rules.MERGED)
            return
        task.branch = request.source_branch
        task.pr_number = request.number
        session.add(
            TaskRun(
                task_id=task.id,
                kind="worker",
                attempt=1,
                model="-",
                state=AgentOutcome.DONE.value,
                head_sha=request.head_sha,
                finished_at=self._clock(),
                log_tail=f"restored {tag}",
            )
        )
        session.commit()
        self._set_state(session, task, rules.CI)

    # --- milestones and demo --------------------------------------------------------------

    def _advance_milestones(self, project_id: uuid.UUID) -> None:
        """Build the milestones whose tasks are all merged; follow the previews being built."""
        if self._preview is None:
            return
        with self._sessions() as session:
            project = session.get(Project, project_id)
            if project is None or project.phase != "building":
                return
            tasks = list(session.scalars(select(Task).where(Task.project_id == project_id)))
            for milestone in demo.milestones_of(session, project_id):
                try:
                    mine = [t for t in tasks if t.milestone == milestone.ref]
                    if milestone.status == demo.PENDING:
                        self._build_milestone(session, project, milestone, mine)
                    elif milestone.preview_state == PreviewState.BUILDING.value:
                        self._follow_preview(session, project, milestone)
                except Exception:
                    session.rollback()
                    log.exception("milestone step failed for %s %s", project_id, milestone.ref)

    def _build_milestone(
        self, session: Session, project: Project, milestone: Milestone, tasks: list[Task]
    ) -> None:
        """pending -> built: tag the default branch, deploy the tag, remember the path.

        Resumable: the tag is stored only once git has it, and a milestone with a tag but not
        `built` yet is simply deployed again (deploying twice is a no-op for the service).
        """
        if self._preview is None or not any(t.kind == "demo" for t in tasks):
            return
        if not tasks or any(t.state != rules.MERGED for t in tasks):
            return
        if milestone.tag is None:
            name = demo.tag_name(milestone)
            try:
                self._git.tag(self._repo(project), name, self._settings.base_branch)
            except TagExists:
                pass  # tagged by an attempt that died before storing the name
            except Exception:
                log.warning("could not tag %s of %s", milestone.ref, project.id, exc_info=True)
                return
            milestone.tag = name
            session.commit()
        request = PreviewRequest(
            project.id, milestone.ref, project.repo_clone_url or "", milestone.tag
        )
        try:
            status = self._preview.deploy(request)
            state, path = status.state.value, status.path
        except PreviewUnavailable:
            log.warning("preview service unreachable, %s will be deployed later", milestone.ref)
            return
        except PreviewRejected:
            log.warning("preview service refused %s of %s", milestone.ref, project.id)
            state, path = PreviewState.FAILED.value, f"/demo/{project.id}/{milestone.ref}/"
        milestone.status = demo.BUILT
        milestone.built_at = self._clock()
        milestone.preview_path = path
        milestone.preview_state = state
        session.commit()
        demo.emit_milestone(self._emit, project.id, milestone)

    def _follow_preview(self, session: Session, project: Project, milestone: Milestone) -> None:
        if self._preview is None:
            return
        try:
            status = self._preview.status(project.id, milestone.ref)
            if status is None:  # the service forgot it (reset): ask again
                status = self._preview.deploy(
                    PreviewRequest(
                        project.id, milestone.ref, project.repo_clone_url or "", milestone.tag or ""
                    )
                )
        except (PreviewUnavailable, PreviewRejected):
            return
        if status.state.value != milestone.preview_state:
            milestone.preview_state = status.state.value
            session.commit()
            demo.emit_milestone(self._emit, project.id, milestone)

    def run_revert_job(self, project_id: uuid.UUID, ref: str) -> bool:
        """The `revert` job: re-open the milestone (and later ones) and queue the restore."""
        self._emit(project_id, "job.started", {"kind": "revert"})
        try:
            with self._sessions() as session:
                project = session.get(Project, project_id)
                if project is None:
                    raise demo.DemoError(404, "not_found")
                reopened = demo.apply_revert(session, self._emit, project, ref, self._stop_run)
            if self._preview is not None:
                for name in reopened:
                    try:
                        self._preview.remove(project_id, name)
                    except Exception:
                        log.warning("could not remove the preview of %s", name, exc_info=True)
        except demo.DemoError as exc:
            self._emit(project_id, "job.failed", {"kind": "revert", "code": exc.code})
            return False
        except Exception:
            log.exception("unexpected error while reverting %s", project_id)
            self._emit(project_id, "job.failed", {"kind": "revert", "code": "internal_error"})
            return False
        return True

    def _stop_run(self, run_id: str) -> None:
        self._agents.stop(run_id)
