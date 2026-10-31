"""The fake pack: the whole build loop on in-memory fakes (`COBBLE_PACK_MODE=fake`).

For development and the browser tests only (ADR 0007). A started project runs the real
scheduler against a fake git server, CI, agent runner and preview service, so the loop
"tasks -> merge -> milestone demo -> comment / validate / revert" plays in seconds without
Docker, a git server, a CI or a model. Nothing here is a mock of the scheduler itself.

The fake agent runner is time based: a run lasts a few steps of `COBBLE_FAKE_STEP_S` seconds,
reveals believable log lines as it goes, then ends `done`. It is deterministic (no randomness)
and, being in memory, does not survive a restart of the worker (the scheduler then retries the
lost runs, as it would with the real service).
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass

from cobble.capabilities.agent import (
    AgentOutcome,
    AgentResult,
    AgentRunNotFound,
    AgentTask,
    run_blocking,
)
from cobble.capabilities.ci import CIState
from cobble.capabilities.fakes import FakeCIProvider, FakeGitProvider
from cobble.capabilities.fakes_preview import FakePreviewProvider
from cobble.capabilities.git import RepoRef, cap_diff
from cobble.capabilities.llm import Role
from cobble.config import Settings

log = logging.getLogger(__name__)

BANNER = (
    "COBBLE_PACK_MODE=fake: no real git server, CI, agent or model is used. "
    "Development and tests only; never use this mode for real projects."
)
FAKE_RUN_TOKEN_SECRET = "fake-pack-mode-run-token-secret"  # noqa: S105 - nothing it signs is real
FAKE_RUN_PREFIX = "fake"
_MARKER = re.compile(r"\[cobble-task:([^:\]]+):")


def _script(role: str, ref: str, branch: str) -> list[str]:
    """The lines a simulated run prints, one per step (a function of the run id alone)."""
    if role == Role.TEST_WRITER.value:
        return [
            f"clone the default branch and create branch {branch}",
            f"[{ref}] reading the acceptance criteria",
            f"[{ref}] writing the tests; they fail as expected before the implementation",
            f"commit and push {branch}",
        ]
    return [
        f"clone the default branch and create branch {branch}",
        f"[{ref}] reading the tests and the acceptance criteria",
        f"[{ref}] editing the files of the task",
        "running the tests: all passed",
        f"commit and push {branch}",
    ]


@dataclass(frozen=True)
class _Run:
    started_ms: int
    role: str
    ref: str
    branch: str

    @property
    def lines(self) -> list[str]:
        return _script(self.role, self.ref, self.branch)

    @property
    def head_sha(self) -> str:
        return f"{self.branch}@{self.started_ms}"


def _parse(run_id: str) -> _Run:
    parts = run_id.split(".", 4)
    try:
        if parts[0] != FAKE_RUN_PREFIX or len(parts) != 5:
            raise ValueError(run_id)
        return _Run(int(parts[1]), parts[2], parts[3], parts[4])
    except ValueError:
        raise AgentRunNotFound(run_id) from None


class SimulatedAgentRunner:
    """AgentRunner whose runs last `len(script) * step_s` seconds and always succeed.

    Stateless: the run id carries everything (start time, role, task reference, branch), so
    the API process and the worker process answer the same for the same id. `stop` does nothing
    here: the scheduler records a stopped run in its own table and stops following it.
    """

    def __init__(self, step_s: float = 0.3, *, clock: Callable[[], float] = time.time) -> None:
        self.step_s = max(step_s, 0.0)
        self._clock = clock

    def start(self, task: AgentTask) -> str:
        match = _MARKER.search(task.marker or task.instructions)
        ref = match.group(1) if match else "task"
        started_ms = int(self._clock() * 1000)
        return f"{FAKE_RUN_PREFIX}.{started_ms}.{task.role.value}.{ref}.{task.branch}"

    def _elapsed(self, run: _Run) -> float:
        return self._clock() - run.started_ms / 1000

    def _revealed(self, run: _Run) -> int:
        if self.step_s == 0:
            return len(run.lines)
        return min(len(run.lines), int(self._elapsed(run) / self.step_s) + 1)

    def _text(self, run: _Run) -> str:
        return "".join(f"{line}\n" for line in run.lines[: self._revealed(run)])

    def poll(self, run_id: str) -> AgentResult | None:
        run = _parse(run_id)
        if self._elapsed(run) < len(run.lines) * self.step_s:
            return None
        return AgentResult(
            AgentOutcome.DONE,
            iterations=len(run.lines) - 2,
            log=self._text(run),
            head_sha=run.head_sha,
            exit_code=0,
        )

    def stop(self, run_id: str) -> None:
        _parse(run_id)

    def logs(self, run_id: str, offset: int = 0) -> tuple[str, int]:
        text = self._text(_parse(run_id))
        return text[max(offset, 0) :], len(text)

    def run(self, task: AgentTask) -> AgentResult:
        return run_blocking(self, task, interval_s=self.step_s or 0.01)


class StatelessFakeGit(FakeGitProvider):
    """FakeGitProvider whose diff depends on its arguments only (API and worker agree)."""

    def diff(
        self, repo: RepoRef, base: str, head: str, *, request_number: int | None = None
    ) -> tuple[str, bool]:
        name = head.removeprefix("task/").replace("/", "-")
        text = (
            f"diff --git a/app/{name}.py b/app/{name}.py\n"
            "new file mode 100644\n"
            "--- /dev/null\n"
            f"+++ b/app/{name}.py\n"
            "@@ -0,0 +1,3 @@\n"
            f'+"""Change of {head} (fake pack)."""\n'
            "+\n"
            f"+VALUE = {len(head)}\n"
        )
        return cap_diff(text)


class FakePackServices:
    """What `build_fake_services` returns: the same attributes as the real PackServices."""

    def __init__(
        self,
        git: FakeGitProvider,
        ci: FakeCIProvider,
        agents: SimulatedAgentRunner,
        preview: FakePreviewProvider,
    ) -> None:
        self.git = git
        self.ci = ci
        self.agents = agents
        self.preview = preview


def build_fake_services(settings: Settings) -> FakePackServices:
    log.warning(BANNER)
    ci = FakeCIProvider(default=CIState.SUCCESS)
    return FakePackServices(
        StatelessFakeGit(ci), ci, SimulatedAgentRunner(settings.fake_step_s), FakePreviewProvider()
    )
