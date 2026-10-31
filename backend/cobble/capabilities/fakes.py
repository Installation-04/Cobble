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
from .git import MergeRefused, MergeRequestRef, RepoRef, cap_diff
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
        self.restores: list[tuple[str, str, str]] = []  # (repo name, tag, message)
        self.restore_nothing = False  # restore_tag finds the tree already in place
        self.diffs: dict[tuple[str, str], str] = {}  # (repo name, head branch) -> unified diff
        self.diff_calls: list[tuple[str, str, str, int | None]] = []
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

    def restore_tag(self, repo: RepoRef, tag: str, message: str) -> MergeRequestRef | None:
        self.restores.append((repo.name, tag, message))
        if self.restore_nothing:
            return None
        return self.open_merge_request(repo, f"restore/{tag}", "main", message)

    def diff(
        self, repo: RepoRef, base: str, head: str, *, request_number: int | None = None
    ) -> tuple[str, bool]:
        """`diffs[(repo, head)]` when set, else a small deterministic diff for a branch that
        has a merge request, else nothing (the branch was never pushed)."""
        self.diff_calls.append((repo.name, base, head, request_number))
        text = self.diffs.get((repo.name, head))
        if text is None:
            if (repo.name, head, base) not in self.opened:
                return "", False
            text = (
                f"diff --git a/{head}.txt b/{head}.txt\n"
                "new file mode 100644\n"
                "--- /dev/null\n"
                f"+++ b/{head}.txt\n"
                "@@ -0,0 +1 @@\n"
                f"+change on {head}\n"
            )
        return cap_diff(text)


class FakeCIProvider:
    """CI results per ref. A ref `branch@n` (the fake agent's head sha) falls back to `branch`."""

    def __init__(self, default: CIState = CIState.PENDING) -> None:
        self.default = default  # the state of a ref with no explicit result
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
        return CIStatus(self.default)

    def wait(self, repo: RepoRef, ref: str, timeout_s: float) -> CIStatus:
        return self.status(repo, ref)


_MARKER = re.compile(r"\[cobble-task:([^:\]]+):([^:\]]+):(\d+)\]")


class FakeAgentRunner:
    """Scripted, non-blocking agent runs.

        `script` maps `(task ref, role, attempt)` (read from the run's marker) to an outcome;
    other runs end with `outcome`. A run answers `None` to its first `polls_before_done` polls.
    Set `unavailable` to simulate an unreachable service, add run ids to `lost` to make the
    service forget them. The head sha of a successful worker run is `<branch>@<attempt>`
    (attempts count per branch from 1), that of a test-writer run `<branch>@0`.
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
        count = 0
        if task.role is Role.WORKER:
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

    def logs(self, run_id: str, offset: int = 0) -> tuple[str, int]:
        """Deterministic log lines; the first line is the one `poll` reports as the log."""
        if self.unavailable:
            raise AgentUnavailable("fake agent service is down")
        if run_id in self.lost or run_id not in self._results:
            raise AgentRunNotFound(run_id)
        task = self.runs[int(run_id.removeprefix("run-")) - 1]
        lines = [
            f"fake log of {run_id}",
            f"$ {task.role.value} on {task.branch}",
            f"iteration 1: {self._results[run_id].outcome.value}",
        ]
        if run_id in self.stopped:
            lines.append("stopped on request")
        text = "\n".join(lines) + "\n"
        return text[max(offset, 0) :], len(text)

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
