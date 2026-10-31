"""In-memory implementations of the capabilities, for tests and local development."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

from .agent import AgentOutcome, AgentResult, AgentTask
from .ci import CIState, CIStatus
from .git import MergeRefused, MergeRequestRef, RepoRef
from .llm import ChatResult, Role


class FakeGitProvider:
    """Merges only when the paired FakeCIProvider reports success for the head ref."""

    def __init__(self, ci: FakeCIProvider | None = None) -> None:
        self.ci = ci
        self.repos: dict[str, Path] = {}
        self.merged: list[MergeRequestRef] = []
        self.tags: list[tuple[str, str, str]] = []
        self._numbers = 0

    def create_repo_from_template(self, name: str, template_dir: Path) -> RepoRef:
        self.repos[name] = template_dir
        return RepoRef(name=name, clone_url=f"fake://{name}.git")

    def open_merge_request(
        self, repo: RepoRef, source_branch: str, target_branch: str, title: str
    ) -> MergeRequestRef:
        self._numbers += 1
        return MergeRequestRef(repo, self._numbers, source_branch, target_branch)

    def merge(self, request: MergeRequestRef) -> None:
        if self.ci is not None:
            status = self.ci.status(request.repo, request.source_branch)
            if status.state is not CIState.SUCCESS:
                raise MergeRefused(f"CI is {status.state.value}")
        self.merged.append(request)

    def tag(self, repo: RepoRef, name: str, ref: str) -> None:
        self.tags.append((repo.name, name, ref))


class FakeCIProvider:
    def __init__(self) -> None:
        self.active: set[str] = set()
        self.results: dict[tuple[str, str], CIState] = {}

    def set_result(self, repo: RepoRef, ref: str, state: CIState) -> None:
        self.results[(repo.name, ref)] = state

    def activate(self, repo: RepoRef) -> None:
        self.active.add(repo.name)

    def status(self, repo: RepoRef, ref: str) -> CIStatus:
        return CIStatus(self.results.get((repo.name, ref), CIState.PENDING))

    def wait(self, repo: RepoRef, ref: str, timeout_s: float) -> CIStatus:
        return self.status(repo, ref)


class FakeAgentRunner:
    def __init__(self, outcome: AgentOutcome = AgentOutcome.DONE) -> None:
        self.outcome = outcome
        self.runs: list[AgentTask] = []
        self.stopped: list[uuid.UUID] = []

    def run(self, task: AgentTask) -> AgentResult:
        self.runs.append(task)
        return AgentResult(self.outcome, iterations=1)

    def stop(self, task_id: uuid.UUID) -> None:
        self.stopped.append(task_id)


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
