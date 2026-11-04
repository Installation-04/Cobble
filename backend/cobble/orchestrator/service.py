"""Planner service: interview replies, spec and plan generation.

Everything goes through the `LLMClient` capability (the cost router in production, a fake in
tests). Each public method does one job end to end: call the model, store the result, move
the project phase, publish events on the project's stream. `run_job` wraps them with the
`job.started` / `job.failed` events and maps failures to the codes of ADR 0005.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from contextvars import ContextVar
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from redis import Redis
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, sessionmaker

from cobble.capabilities.llm import LLMClient, Role
from cobble.config import Settings
from cobble.db import JobCheckpoint, Message, Milestone, Plan, Project, Spec, Task, User
from cobble.events import publish_project
from cobble.router.budget import BudgetExceeded
from cobble.router.costs import LocalOnlyUnavailable
from cobble.router.gateway import GatewayError

from . import prompts
from .estimate import estimate_from_settings
from .plan_schema import Plan as ParsedPlan
from .plan_schema import PlanInvalid, parse_plan_reply

log = logging.getLogger(__name__)

JOB_KINDS = ("reply", "spec", "plan", "explain")
EXPLAIN_ROLE = Role.REVIEWER  # reads what was built and describes it (ADR 0017)

# A checkpoint older than this belongs to a job nobody replayed: it is ignored and purged.
CHECKPOINT_TTL = timedelta(hours=1)
# Set while `run_job` runs: LLM steps are only checkpointed inside a job (ADR 0016).
_in_job: ContextVar[bool] = ContextVar("cobble_planner_in_job", default=False)


class JobError(Exception):
    """A job failed for a reason the user should see (`code` goes in `job.failed`)."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def message_payload(message: Message) -> dict[str, Any]:
    return {
        "id": str(message.id),
        "role": message.role,
        "content": message.content,
        "created_at": message.created_at.isoformat(),
    }


class PlannerService:
    def __init__(
        self,
        sessions: sessionmaker[Session],
        llm: LLMClient,
        events: Redis | None,
        settings: Settings,
    ) -> None:
        self._sessions = sessions
        self._llm = llm
        self._events = events
        self._settings = settings

    # --- jobs ---------------------------------------------------------------------------

    def run_job(
        self,
        kind: str,
        project_id: uuid.UUID,
        *,
        feedback: str | None = None,
        message_id: str | None = None,
        ref: str | None = None,
        force: bool = False,
    ) -> bool:
        """Run one job. Never raises: failures become a `job.failed` event. True on success."""
        self._emit(project_id, "job.started", {"kind": kind})
        token = _in_job.set(True)
        try:
            ok = self._run_job(kind, project_id, feedback, message_id, ref, force)
        finally:
            _in_job.reset(token)
        # Only a job that ended (either way) clears its steps; a process killed mid-job leaves
        # them for the replay.
        self._clear_checkpoints(project_id)
        return ok

    def _run_job(
        self,
        kind: str,
        project_id: uuid.UUID,
        feedback: str | None,
        message_id: str | None,
        ref: str | None = None,
        force: bool = False,
    ) -> bool:
        try:
            if kind == "reply":
                self.reply(project_id, message_id)
            elif kind == "spec":
                self.generate_spec(project_id, feedback)
            elif kind == "plan":
                self.generate_plan(project_id, feedback)
            elif kind == "explain":
                self.explain_milestone(project_id, ref or "", force=force)
            else:
                raise JobError("unknown_job")
        except BudgetExceeded:
            return self._failed(kind, project_id, "budget_reached")
        except LocalOnlyUnavailable:
            return self._failed(kind, project_id, "local_only_unavailable")
        except (GatewayError, httpx.HTTPError):
            log.warning("model gateway error in %s job", kind, exc_info=True)
            return self._failed(kind, project_id, "llm_error")
        except JobError as exc:
            return self._failed(kind, project_id, exc.code)
        except Exception:
            log.exception("unexpected error in %s job", kind)
            return self._failed(kind, project_id, "internal_error")
        return True

    # --- checkpoints (ADR 0016) ---------------------------------------------------------

    def _chat(
        self, role: Role, messages: list[dict[str, Any]], project_id: uuid.UUID, step: int = 0
    ) -> str:
        """The model's answer; a job replayed after a crash reuses the one it already paid for."""
        if not _in_job.get():
            return self._llm.chat(role, messages, project_id=project_id).content
        key = hashlib.sha256(
            json.dumps([step, str(role), messages], sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()
        now = datetime.now(UTC)
        with self._sessions() as db:
            row = db.get(JobCheckpoint, (project_id, key))
            if row is not None:
                created = row.created_at
                if created.tzinfo is None:
                    created = created.replace(tzinfo=UTC)
                if now - created <= CHECKPOINT_TTL:
                    log.info("job step reused from its checkpoint for project %s", project_id)
                    return row.content
                db.delete(row)
                db.commit()
        content = self._llm.chat(role, messages, project_id=project_id).content
        with self._sessions() as db:
            db.merge(JobCheckpoint(project_id=project_id, key=key, content=content, created_at=now))
            db.commit()
        return content

    def _clear_checkpoints(self, project_id: uuid.UUID) -> None:
        """The job ended (either way): its steps must not leak into the next one."""
        try:
            with self._sessions() as db:
                db.execute(delete(JobCheckpoint).where(JobCheckpoint.project_id == project_id))
                db.commit()
        except Exception:
            log.warning("could not clear the job checkpoints of %s", project_id, exc_info=True)

    def _failed(self, kind: str, project_id: uuid.UUID, code: str) -> bool:
        self._emit(project_id, "job.failed", {"kind": kind, "code": code})
        return False

    def _emit(self, project_id: uuid.UUID, event: str, payload: dict[str, Any]) -> None:
        if self._events is not None:
            publish_project(self._events, project_id, event, payload)

    # --- interview ----------------------------------------------------------------------

    def reply(self, project_id: uuid.UUID, message_id: str | None = None) -> None:
        """Answer the user's last message. `message_id` makes a replayed job a no-op."""
        with self._sessions() as db:
            project = db.get(Project, project_id)
            if project is None or project.phase != "interview":
                return
            history = _history(db, project_id)
            lang = _language(db, project)
        if not history or history[-1]["role"] != "user":
            return  # already answered (a job replayed after a crash)
        if message_id is not None and history[-1]["id"] != message_id:
            return
        content = self._chat(Role.PLANNER, prompts.interview_messages(history, lang), project_id)
        with self._sessions() as db:
            message = Message(project_id=project_id, role="assistant", content=content)
            db.add(message)
            db.commit()
            db.refresh(message)
            payload = message_payload(message)
        self._emit(project_id, "message.created", {"message": payload})

    # --- spec ---------------------------------------------------------------------------

    def generate_spec(self, project_id: uuid.UUID, feedback: str | None = None) -> None:
        with self._sessions() as db:
            project = db.get(Project, project_id)
            if project is None or project.phase not in ("interview", "spec_review"):
                return
            history = _history(db, project_id)
            lang = _language(db, project)
            previous = _latest(db, Spec, project_id)
            previous_spec = previous.content if previous else None
        content = self._chat(
            Role.PLANNER,
            prompts.spec_messages(history, lang, feedback=feedback, previous_spec=previous_spec),
            project_id,
        )
        with self._sessions() as db:
            version = _next_version(db, Spec, project_id)
            db.add(Spec(project_id=project_id, version=version, content=content.strip()))
            changed = self._set_phase(db, project_id, "spec_review")
            db.commit()
        self._emit(project_id, "spec.updated", {"version": version})
        if changed:
            self._emit(project_id, "phase.changed", {"phase": "spec_review"})

    # --- plan ---------------------------------------------------------------------------

    def generate_plan(self, project_id: uuid.UUID, feedback: str | None = None) -> None:
        with self._sessions() as db:
            project = db.get(Project, project_id)
            if project is None or project.phase not in ("spec_review", "plan_review"):
                return
            spec = _latest(db, Spec, project_id)
            if spec is None or spec.status != "approved":
                return
            lang = _language(db, project)
            previous = _latest(db, Plan, project_id)
            previous_plan = _plan_text(previous.plan) if previous else None
            spec_text = spec.content
        base = prompts.plan_messages(
            spec_text, lang, feedback=feedback, previous_plan=previous_plan
        )
        messages = base
        errors: list[str] = []
        parsed: ParsedPlan | None = None
        for attempt in range(prompts.MAX_PLAN_ATTEMPTS):
            reply = self._chat(Role.PLANNER, messages, project_id, attempt)
            try:
                parsed = parse_plan_reply(reply)
                break
            except PlanInvalid as exc:
                errors = exc.errors
                log.info("plan rejected (attempt %d): %s", attempt + 1, errors)
                messages = prompts.retry_messages(base, reply, errors)
        if parsed is None:
            raise JobError("plan_invalid")
        estimate = estimate_from_settings(parsed, self._settings)
        with self._sessions() as db:
            version = _next_version(db, Plan, project_id)
            db.add(
                Plan(
                    project_id=project_id,
                    version=version,
                    plan=parsed.model_dump(mode="json"),
                    estimate=estimate,
                )
            )
            changed = self._set_phase(db, project_id, "plan_review")
            db.commit()
        self._emit(project_id, "plan.updated", {"version": version})
        if changed:
            self._emit(project_id, "phase.changed", {"phase": "plan_review"})

    # --- explain mode (ADR 0017) --------------------------------------------------------

    def explain_milestone(self, project_id: uuid.UUID, ref: str, *, force: bool = False) -> None:
        """Write the plain-language summary of a built milestone, in the user's language.

        A no-op (so a replayed or duplicated job costs nothing) when the mode is off, the
        milestone is not built, or it already has its summary and `force` is not set.
        """
        with self._sessions() as db:
            project = db.get(Project, project_id)
            if project is None or not project.explain_mode:
                return
            milestone = db.scalars(
                select(Milestone).where(Milestone.project_id == project_id, Milestone.ref == ref)
            ).first()
            if milestone is None or milestone.status == "pending":
                return
            if milestone.explanation and not force:
                return
            lang = _language(db, project)
            tasks = [
                (t.title, list(t.acceptance or []))
                for t in db.scalars(
                    select(Task)
                    .where(
                        Task.project_id == project_id,
                        Task.milestone == ref,
                        Task.kind != "revert",
                    )
                    .order_by(Task.ref)
                )
            ]
            messages = prompts.explain_messages(
                project.name, (milestone.ref, milestone.title), tasks, lang
            )
        text = self._chat(EXPLAIN_ROLE, messages, project_id).strip()
        if not text:
            raise JobError("empty_explanation")
        with self._sessions() as db:
            milestone = db.scalars(
                select(Milestone).where(Milestone.project_id == project_id, Milestone.ref == ref)
            ).first()
            if milestone is None or milestone.status == "pending":
                return  # re-opened while the model was answering: the summary would be stale
            milestone.explanation = text
            status = milestone.status
            db.commit()
        self._emit(
            project_id, "milestone.updated", {"ref": ref, "status": status, "explained": True}
        )

    # --- shared -------------------------------------------------------------------------

    @staticmethod
    def _set_phase(db: Session, project_id: uuid.UUID, phase: str) -> bool:
        project = db.get(Project, project_id)
        if project is None or project.phase == phase:
            return False
        project.phase = phase
        return True


def _history(db: Session, project_id: uuid.UUID) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(Message)
        .where(Message.project_id == project_id)
        .order_by(Message.created_at, Message.id)
    )
    return [{"id": str(m.id), "role": m.role, "content": m.content} for m in rows]


def _language(db: Session, project: Project) -> str:
    return db.scalar(select(User.lang).where(User.id == project.owner_id)) or "en"


def _latest(db: Session, model: type[Spec] | type[Plan], project_id: uuid.UUID) -> Any:
    return db.scalars(
        select(model).where(model.project_id == project_id).order_by(model.version.desc()).limit(1)
    ).first()


def _next_version(db: Session, model: type[Spec] | type[Plan], project_id: uuid.UUID) -> int:
    top = db.scalar(select(func.max(model.version)).where(model.project_id == project_id))
    return (top or 0) + 1


def _plan_text(plan: dict[str, Any]) -> str:
    return json.dumps(plan, indent=2, sort_keys=True, ensure_ascii=False)
