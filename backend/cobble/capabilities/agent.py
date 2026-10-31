"""Agent runner capability: run one task in an isolated container and return its outcome.

The scheduler drives runs without blocking: `start` launches a run and returns its id, `poll`
returns None while it is running and the result once it ended, `stop` asks it to end. `run`
is a blocking convenience built on the other three (see `run_blocking`).
"""

from __future__ import annotations

import enum
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

from .llm import Role


class AgentOutcome(enum.StrEnum):
    DONE = "done"  # the agent finished and pushed its branch
    FAILED = "failed"
    TIMEOUT = "timeout"
    LOOP_DETECTED = "loop_detected"
    BUDGET = "budget"  # stopped because the project budget was reached
    STOPPED = "stopped"  # stopped on request (`stop`)


class AgentUnavailable(Exception):
    """The agent service could not be reached or answered with a server error: retry later."""


class AgentRunNotFound(Exception):
    """The agent service does not know this run id (it was lost, for example after a reset)."""


class AgentRejected(Exception):
    """The agent service refused to start the run (bad request or credentials)."""


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
    # Added for the scheduler (ADR 0006); all optional so older callers keep working.
    model: str = ""
    base_branch: str = "main"
    test_command: str = ""
    run_token: str = ""
    marker: str = ""


@dataclass(frozen=True)
class AgentResult:
    outcome: AgentOutcome
    iterations: int = 0
    log: str = ""
    head_sha: str | None = None
    exit_code: int | None = None


class AgentRunner(Protocol):
    def start(self, task: AgentTask) -> str:
        """Launch a run and return its id. Raises AgentUnavailable / AgentRejected."""
        ...

    def poll(self, run_id: str) -> AgentResult | None:
        """None while the run is running, its result once it ended.

        Raises AgentRunNotFound for an unknown run and AgentUnavailable when the service
        cannot be reached.
        """
        ...

    def stop(self, run_id: str) -> None: ...

    def run(self, task: AgentTask) -> AgentResult:
        """Blocking convenience: start, then poll until the run ends."""
        ...


def run_blocking(
    runner: AgentRunner,
    task: AgentTask,
    *,
    interval_s: float = 2.0,
    timeout_s: float | None = None,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> AgentResult:
    """Start a run and wait for its result; stops the run if `timeout_s` expires."""
    run_id = runner.start(task)
    deadline = None if timeout_s is None else clock() + timeout_s
    while True:
        result = runner.poll(run_id)
        if result is not None:
            return result
        if deadline is not None and clock() >= deadline:
            runner.stop(run_id)
            return AgentResult(AgentOutcome.TIMEOUT)
        sleep(interval_s)
