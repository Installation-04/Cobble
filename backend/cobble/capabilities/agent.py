"""Agent runner capability: run one task in an isolated container and return its outcome."""

from __future__ import annotations

import enum
import uuid
from dataclasses import dataclass, field
from typing import Protocol

from .llm import Role


class AgentOutcome(enum.StrEnum):
    DONE = "done"  # the agent finished and pushed its branch
    FAILED = "failed"
    TIMEOUT = "timeout"
    LOOP_DETECTED = "loop_detected"
    BUDGET = "budget"  # stopped because the project budget was reached


@dataclass(frozen=True)
class AgentLimits:
    max_iterations: int = 20
    max_seconds: int = 900
    cpu: float = 1.0
    memory_mb: int = 2048
    pids: int = 256


@dataclass(frozen=True)
class AgentTask:
    task_id: uuid.UUID
    project_id: uuid.UUID
    repo_clone_url: str
    branch: str
    role: Role
    instructions: str
    files: list[str] = field(default_factory=list)
    limits: AgentLimits = field(default_factory=AgentLimits)


@dataclass(frozen=True)
class AgentResult:
    outcome: AgentOutcome
    iterations: int = 0
    log: str = ""


class AgentRunner(Protocol):
    def run(self, task: AgentTask) -> AgentResult: ...

    def stop(self, task_id: uuid.UUID) -> None: ...
