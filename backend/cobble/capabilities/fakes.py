"""In-memory implementations of the capabilities, for tests and local development."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

from .agent import (
    AgentOutcome,
    AgentResult,
    AgentRunNotFound,
    AgentTask,
    AgentUnavailable,
    run_blocking,
)
from .ci import CIState, CIStatus
from .git import MergeRefused, MergeRequestRef, RepoRef
from .llm import ChatResult, Role


class FakeGitProvider:
    """Merges only when the paired FakeCIProvider reports success for the head ref.

    Like the real provider, `open_merge_request` and `merge` are idempotent: asking twice for
    the same branch pair returns the same request, merging a merged request does nothing.
    `merge_calls` still records every attempt, so tests can see a double call.
    """

    def __init__(self, ci: FakeCIProvider | None = None) -> None:
        self.ci = ci
        self.repos: dict[str, Path] = {}
        self.merged: list[MergeRequestRef] = []
        self.merge_calls: list[MergeRequestRef] = []
        self.opened: dict[tuple[str, str, str], MergeRequestRef] = {}
        self.tags: list[tuple[str, str, str]] = []
        self._numbers = 0

    def create_repo_from_template(self, name: str, template_dir: Path) -> RepoRef:
        self.repos[name] = template_dir
        return RepoRef(name=name, clone_url=f"fake://{name}.git")

    def open_merge_request(
        self, repo: RepoRef, source_branch: str, target_branch: str, title: str
    ) -> MergeRequestRef:
        key = (repo.name, source_branch, target_branch)
        if key not in self.opened:
            self._numbers += 1
            self.opened[key] = MergeRequestRef(repo, self._numbers, source_branch, target_branch)
        return self.opened[key]

    def merge(self, request: MergeRequestRef) -> None:
        self.merge_calls.append(request)
        if any(m.repo == request.repo and m.number == request.number for m in self.merged):
            return
        if self.ci is not None:
            status = self.ci.status(request.repo, request.head_sha or request.source_branch)
            if status.state is not CIState.SUCCESS:
                raise MergeRefused(f"CI is {status.state.value}")
        self.merged.append(request)

    def tag(self, repo: RepoRef, name: str, ref: str) -> None:
        self.tags.append((repo.name, name, ref))


class FakeCIProvider:
    """CI results per ref. A ref `branch@n` (the fake agent's head sha) falls back to `branch`."""

    def __init__(self) -> None:
        self.active: set[str] = set()
        self.results: dict[tuple[str, str], CIState] = {}
        self.details: dict[tuple[str, str], str] = {}

    def set_result(self, repo: RepoRef, ref: str, state: CIState, detail: str = "") -> None:
        self.results[(repo.name, ref)] = state
        self.details[(repo.name, ref)] = detail

    def activate(self, repo: RepoRef) -> None:
        self.active.add(repo.name)

    def status(self, repo: RepoRef, ref: str) -> CIStatus:
        for candidate in (ref, ref.split("@", 1)[0]):
            key = (repo.name, candidate)
            if key in self.results:
                return CIStatus(self.results[key], self.details.get(key, ""))
        return CIStatus(CIState.PENDING)

    def wait(self, repo: RepoRef, ref: str, timeout_s: float) -> CIStatus:
        return self.status(repo, ref)


_MARKER = re.compile(r"\[cobble-task:([^:\]]+):([^:\]]+):(\d+)\]")


class FakeAgentRunner:
    """Scripted, non-blocking agent runs.

    `script` maps `(task ref, role, attempt)` (read from the run's marker) to an outcome;
    other runs end with `outcome`. A run answers `None` to its first `polls_before_done` polls.
    Set `unavailable` to simulate an unreachable service, add run ids to `lost` to make the
    service forget them. The head sha of a run is `<branch>@<n>` (n counts the runs per branch).
    """

    def __init__(
        self,
        outcome: AgentOutcome = AgentOutcome.DONE,
        *,
        script: dict[tuple[str, str, int], AgentOutcome] | None = None,
        polls_before_done: int = 0,
    ) -> None:
        self.outcome = outcome
        self.script = dict(script or {})
        self.polls_before_done = polls_before_done
        self.unavailable = False
        self.runs: list[AgentTask] = []
        self.stopped: list[str] = []
        self.lost: set[str] = set()
        self._results: dict[str, AgentResult] = {}
        self._polls: dict[str, int] = {}
        self._per_branch: dict[str, int] = {}

    def _outcome_for(self, task: AgentTask) -> AgentOutcome:
        match = _MARKER.search(task.marker or task.instructions)
        if match:
            key = (match.group(1), match.group(2), int(match.group(3)))
            if key in self.script:
                return self.script[key]
        return self.outcome

    def start(self, task: AgentTask) -> str:
        if self.unavailable:
            raise AgentUnavailable("fake agent service is down")
        self.runs.append(task)
        run_id = f"run-{len(self.runs)}"
        count = self._per_branch.get(task.branch, 0) + 1
        self._per_branch[task.branch] = count
        outcome = self._outcome_for(task)
        self._results[run_id] = AgentResult(
            outcome,
            iterations=1,
            log=f"fake log of {run_id}",
            head_sha=f"{task.branch}@{count}" if outcome is AgentOutcome.DONE else None,
        )
        self._polls[run_id] = 0
        return run_id

    def poll(self, run_id: str) -> AgentResult | None:
        if self.unavailable:
            raise AgentUnavailable("fake agent service is down")
        if run_id in self.lost or run_id not in self._results:
            raise AgentRunNotFound(run_id)
        if run_id in self.stopped:
            return AgentResult(AgentOutcome.STOPPED)
        self._polls[run_id] += 1
        if self._polls[run_id] <= self.polls_before_done:
            return None
        return self._results[run_id]

    def stop(self, run_id: str) -> None:
        self.stopped.append(run_id)

    def run(self, task: AgentTask) -> AgentResult:
        return run_blocking(self, task, sleep=lambda _s: None)


@dataclass
class FakeLLMClient:
    """Returns a fixed reply with a fixed cost, and records every call."""

    reply: str = "ok"
    cost_usd: Decimal = Decimal("0.01")
    calls: list[tuple[Role, list[dict[str, Any]]]] = field(default_factory=list)

    def chat(
        self,
        role: Role,
        messages: list[dict[str, Any]],
        *,
        project_id: uuid.UUID | None = None,
        task_id: uuid.UUID | None = None,
    ) -> ChatResult:
        self.calls.append((role, messages))
        return ChatResult(self.reply, "fake", 1, 1, self.cost_usd, None)
