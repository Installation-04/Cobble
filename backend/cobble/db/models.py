"""Database models."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    false,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class LLMCall(Base):
    """One call to the model gateway, with its tokens and cost."""

    __tablename__ = "llm_calls"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    model: Mapped[str] = mapped_column(String(200), nullable=False)
    role: Mapped[str | None] = mapped_column(String(50))
    project_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, index=True)
    task_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, index=True)
    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    completion_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(14, 8), nullable=False)
    request_id: Mapped[str | None] = mapped_column(String(200))
    # Set when the role's first choice could not answer: the first model that failed, and how
    # many failed before this one answered (nothing is stored for failed attempts: no tokens).
    fallback_from: Mapped[str | None] = mapped_column(String(200))
    fallbacks: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")


class ModelPrice(Base):
    """The last price seen for a model, to notice when a provider changes it (ADR 0013).

    `previous_*` and `changed_at` are set only when a later look found a different price."""

    __tablename__ = "model_prices"

    model: Mapped[str] = mapped_column(String(200), primary_key=True)
    upstream: Mapped[str | None] = mapped_column(String(200))  # the provider's own model name
    prompt_usd: Mapped[Decimal] = mapped_column(Numeric(20, 12), nullable=False)  # per token
    completion_usd: Mapped[Decimal] = mapped_column(Numeric(20, 12), nullable=False)
    free: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    previous_prompt_usd: Mapped[Decimal | None] = mapped_column(Numeric(20, 12))
    previous_completion_usd: Mapped[Decimal | None] = mapped_column(Numeric(20, 12))
    changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )


class JobCheckpoint(Base):
    """The stored answer of one LLM step of a running planner job (ADR 0016).

    Keyed by a digest of the request, so a job replayed after a crash reuses the answer it
    already paid for instead of calling the model again. Rows live only while the job runs.
    """

    __tablename__ = "job_checkpoints"

    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ModelBenchmark(Base):
    """One run of the local model benchmark: how well and how fast a model codes on this machine."""

    __tablename__ = "model_benchmarks"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    model: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)  # of the task set
    quality: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)  # 0..1
    seconds: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    tokens_per_second: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    outcomes: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    # Set in Python too (microseconds) so two runs in the same second sort in the right order.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
        nullable=False,
    )


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _now_col() -> Mapped[datetime]:
    # Set in Python too (microsecond precision) so rows created in the same second sort stably.
    return mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=func.now(), nullable=False
    )


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(254), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(500), nullable=False)
    role: Mapped[str] = mapped_column(
        String(20), nullable=False, default="admin", server_default="admin"
    )
    lang: Mapped[str] = mapped_column(String(5), nullable=False, default="en", server_default="en")
    theme: Mapped[str] = mapped_column(
        String(10), nullable=False, default="system", server_default="system"
    )
    created_at: Mapped[datetime] = _now_col()


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = _now_col()


class ActivationToken(Base):
    __tablename__ = "activation_tokens"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _now_col()
    # Set for a reset link: activating it changes this user's credentials instead of creating one.
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE")
    )


class Folder(Base):
    __tablename__ = "folders"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = _now_col()


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    folder_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("folders.id", ondelete="SET NULL"), index=True
    )
    created_at: Mapped[datetime] = _now_col()
    # Hard spending cap in USD (None = unlimited). A paused project accepts no LLM calls.
    budget_usd: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="active", server_default="active"
    )
    budget_warning_sent: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    # True: no request of this project may reach a model that is not served on this machine
    # (confidential code). Enforced by the cost router, which fails closed.
    local_only: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    # True: before planning, the planner proposes 2-3 mockups and the user picks one (ADR 0018).
    mockups_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    # interview -> spec_review -> plan_review -> ready -> building -> done
    phase: Mapped[str] = mapped_column(
        String(20), nullable=False, default="interview", server_default="interview"
    )
    # The generated project's repository, created when the build starts (ADR 0006).
    repo_name: Mapped[str | None] = mapped_column(String(200))
    repo_clone_url: Mapped[str | None] = mapped_column(Text)


class Message(Base):
    """One message of the interview chat."""

    __tablename__ = "messages"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)  # user | assistant
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = _now_col()


class Spec(Base):
    """A version of the project specification (Markdown)."""

    __tablename__ = "specs"
    __table_args__ = (UniqueConstraint("project_id", "version"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="draft", server_default="draft"
    )  # draft | approved
    created_at: Mapped[datetime] = _now_col()


class MockupVariant(Base):
    """One mockup proposed by the planner: plain text only, never markup (ADR 0018)."""

    __tablename__ = "mockup_variants"
    __table_args__ = (UniqueConstraint("project_id", "position"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    wireframe: Mapped[str] = mapped_column(Text, nullable=False)  # ASCII wireframe
    chosen: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    created_at: Mapped[datetime] = _now_col()


class Plan(Base):
    """A version of the validated plan, with its cost estimate."""

    __tablename__ = "plans"
    __table_args__ = (UniqueConstraint("project_id", "version"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    plan: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    estimate: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="draft", server_default="draft"
    )  # draft | approved
    created_at: Mapped[datetime] = _now_col()


class Task(Base):
    """One task of the approved plan, driven by the scheduler (ADR 0006)."""

    __tablename__ = "tasks"
    __table_args__ = (UniqueConstraint("project_id", "ref"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    ref: Mapped[str] = mapped_column(String(20), nullable=False)  # T-001
    title: Mapped[str] = mapped_column(Text, nullable=False)
    milestone: Mapped[str] = mapped_column(String(20), nullable=False)
    depends_on: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    files: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    acceptance: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    tests: Mapped[str] = mapped_column(Text, nullable=False)
    size: Mapped[str] = mapped_column(String(5), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    # plan (from the approved plan), demo (DEMO-Mx), comment (C-001...), revert (R-001...)
    kind: Mapped[str] = mapped_column(
        String(10), nullable=False, default="plan", server_default="plan"
    )
    # todo, writing_tests, implementing, ci, merged, failed, blocked, paused, stopped
    state: Mapped[str] = mapped_column(
        String(20), nullable=False, default="todo", server_default="todo"
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    escalated: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    branch: Mapped[str | None] = mapped_column(String(200))
    pr_number: Mapped[int | None] = mapped_column(Integer)
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _now_col()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        onupdate=_utcnow,
        server_default=func.now(),
        nullable=False,
    )


class TaskRun(Base):
    """One agent run (test-writer or worker attempt) of a task."""

    __tablename__ = "task_runs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(20), nullable=False)  # test-writer | worker
    attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    model: Mapped[str] = mapped_column(String(200), nullable=False)
    # pending (not started yet), running, then the outcome: done, failed, timeout,
    # loop_detected, stopped, budget, lost
    state: Mapped[str] = mapped_column(String(20), nullable=False)
    agent_run_id: Mapped[str | None] = mapped_column(String(200))
    iterations: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    head_sha: Mapped[str | None] = mapped_column(String(100))
    started_at: Mapped[datetime] = _now_col()
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    log_tail: Mapped[str | None] = mapped_column(Text)


class Milestone(Base):
    """A milestone of the plan with its demo (ADR 0007)."""

    __tablename__ = "milestones"
    __table_args__ = (UniqueConstraint("project_id", "ref"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    ref: Mapped[str] = mapped_column(String(20), nullable=False)  # M1
    title: Mapped[str] = mapped_column(Text, nullable=False)
    # pending -> built -> validated; a revert returns to pending
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", server_default="pending"
    )
    tag: Mapped[str | None] = mapped_column(String(100))  # milestone-M1, milestone-M1-r2...
    preview_path: Mapped[str | None] = mapped_column(Text)
    # building | running | failed: last known state of the deployed preview
    preview_state: Mapped[str | None] = mapped_column(String(20))
    # Incremented each time the milestone is re-opened (comment, revert): names the next tag.
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    built_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Module(Base):
    """An installed (or installing) module of the store (ADR 0008)."""

    __tablename__ = "modules"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)  # the manifest id
    version: Mapped[str] = mapped_column(String(40), nullable=False)
    variant: Mapped[str | None] = mapped_column(String(20))
    # True when the user asked for it; False when it is only a dependency of another module.
    explicit: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    # installing | running | failed | removing
    state: Mapped[str] = mapped_column(
        String(20), nullable=False, default="installing", server_default="installing"
    )
    settings: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict, server_default="{}"
    )
    # An error *code* (translated by the UI), never a message that could carry a secret.
    last_error: Mapped[str | None] = mapped_column(String(100))
    installed_at: Mapped[datetime] = _now_col()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        server_default=func.now(),
        onupdate=_utcnow,
        nullable=False,
    )


class ModuleSecret(Base):
    """A secret of a module, encrypted by the module-manager's vault (AES-256-GCM)."""

    __tablename__ = "module_secrets"

    module_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("modules.id", ondelete="CASCADE"), primary_key=True
    )
    key: Mapped[str] = mapped_column(String(40), primary_key=True)
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    nonce: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    key_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    created_at: Mapped[datetime] = _now_col()


class LlmConnection(Base):
    """A language-model service the administrator connected with an API key.

    The key is encrypted by the module-manager's vault (bound to the connection's name), never
    stored in clear and never returned by any API. `name` is what the gateway exposes and what
    the default model refers to.
    """

    __tablename__ = "llm_connections"

    name: Mapped[str] = mapped_column(String(40), primary_key=True)
    # openai | anthropic | openrouter | custom (an OpenAI-compatible service at `base_url`)
    provider: Mapped[str] = mapped_column(String(20), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    base_url: Mapped[str | None] = mapped_column(String(300))
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    nonce: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    key_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    created_at: Mapped[datetime] = _now_col()


class ModuleLink(Base):
    """A consumer module linked to a provider module through a capability."""

    __tablename__ = "module_links"
    __table_args__ = (UniqueConstraint("consumer", "provider", "capability"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    consumer: Mapped[str] = mapped_column(
        String(40), ForeignKey("modules.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider: Mapped[str] = mapped_column(
        String(40), ForeignKey("modules.id", ondelete="CASCADE"), nullable=False, index=True
    )
    capability: Mapped[str] = mapped_column(String(40), nullable=False)
    # pending | linked | failed
    state: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", server_default="pending"
    )
    created_at: Mapped[datetime] = _now_col()


class ModuleEvent(Base):
    """The history of what the module-manager did (kept after an uninstall)."""

    __tablename__ = "module_events"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # No foreign key: the history must outlive the module.
    module_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    at: Mapped[datetime] = _now_col()
    # install | uninstall | link | unlink | step | rollback
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    step: Mapped[str | None] = mapped_column(String(30))
    # ok | error
    outcome: Mapped[str] = mapped_column(
        String(10), nullable=False, default="ok", server_default="ok"
    )
    code: Mapped[str | None] = mapped_column(String(100))  # translated by the UI
    params: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict, server_default="{}"
    )


class PlatformState(Base):
    """A single row: whether the first-run setup is done and the modules generation counter.

    `modules_generation` is bumped on every change of the installed modules; the worker compares
    it with the one it built its providers from and rebuilds them when it moved.
    """

    __tablename__ = "platform_state"
    __table_args__ = (CheckConstraint("id = 1", name="ck_platform_state_single_row"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    setup_completed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    setup_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    modules_generation: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    # The model used when a role has none of its own; None means the configured one (`fake` in
    # development). Set when a model connection is made the default.
    default_model: Mapped[str | None] = mapped_column(String(40))
    # Per role, the ordered models to try: the first one, then each fallback if the previous
    # one cannot answer (`{"worker": ["local", "cheap-api"]}`). None: no routes were set.
    role_routes: Mapped[dict[str, list[str]] | None] = mapped_column(JSON)
