"""Request and response models of the agent-service HTTP API (ADR 0006)."""

from __future__ import annotations

import re
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

State = Literal["running", "done", "failed", "timeout", "loop_detected", "stopped"]
TERMINAL_STATES: frozenset[str] = frozenset(
    {"done", "failed", "timeout", "loop_detected", "stopped"}
)

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$")
_BRANCH = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,127}$")
_MODEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/@+-]{0,127}$")


def _check_branch(value: str) -> str:
    if (
        not _BRANCH.match(value)
        or ".." in value
        or "//" in value
        or value.endswith(("/", ".lock", "."))
        or "/." in value
    ):
        raise ValueError("invalid branch name")
    return value


class Limits(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_iterations: Annotated[int, Field(ge=1, le=100)] = 8
    max_seconds: Annotated[int, Field(ge=10, le=24 * 3600)] = 900
    cpu: Annotated[float, Field(gt=0, le=64)] = 1.0
    memory_mb: Annotated[int, Field(ge=128, le=262144)] = 2048
    pids: Annotated[int, Field(ge=16, le=65536)] = 512


class RunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str
    project_id: str
    repo_clone_url: Annotated[str, Field(min_length=1, max_length=2048)]
    base_branch: str = "main"
    branch: str
    role: str
    model: str
    instructions: Annotated[str, Field(max_length=200_000)]
    files: Annotated[list[str], Field(max_length=200)] = []
    test_command: Annotated[str, Field(max_length=4000)] = ""
    limits: Limits = Limits()
    run_token: Annotated[str, Field(min_length=8, max_length=4096, repr=False)]
    marker: Annotated[str, Field(min_length=1, max_length=300)]

    @field_validator("task_id", "project_id", "role")
    @classmethod
    def _ids(cls, v: str) -> str:
        if not _ID.match(v):
            raise ValueError("invalid identifier")
        return v

    @field_validator("branch", "base_branch")
    @classmethod
    def _branches(cls, v: str) -> str:
        return _check_branch(v)

    @field_validator("model")
    @classmethod
    def _model(cls, v: str) -> str:
        if not _MODEL.match(v):
            raise ValueError("invalid model alias")
        return v

    @field_validator("files")
    @classmethod
    def _files(cls, v: list[str]) -> list[str]:
        for path in v:
            if (
                not path
                or path.startswith("/")
                or ".." in path.split("/")
                or "\n" in path
                or "\x00" in path
                or len(path) > 512
            ):
                raise ValueError("invalid file path")
        return v

    @field_validator("test_command")
    @classmethod
    def _test(cls, v: str) -> str:
        if "\x00" in v:
            raise ValueError("invalid test command")
        return v

    @field_validator("marker")
    @classmethod
    def _marker(cls, v: str) -> str:
        if "\n" in v or "\r" in v or "\x00" in v:
            raise ValueError("marker must be a single line")
        return v


class RunCreated(BaseModel):
    run_id: str


class RunStatus(BaseModel):
    """`state`, `iterations`, `exit_code`, `head_sha`, `log_tail` are the ADR 0006 fields; the
    others are additive details for the scheduler and the UI."""

    run_id: str
    state: State
    iterations: int
    exit_code: int | None
    head_sha: str | None
    log_tail: str
    reason: str | None = None
    commits: int = 0
    diff_stat: str = ""
    pushed: bool = False
    started_at: float
    finished_at: float | None = None
    detail: dict[str, Any] = {}
