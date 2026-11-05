"""The bench loop: one reference project after another, through the public API only.

For each project: create it, cap its budget, send the frozen specification as the interview,
generate and approve the spec and the plan, start the build, follow it (validating each demo
like the owner would) until the project is done, a task fails, the budget stops it or time runs
out; then fetch the generated code, run the hidden tests on it, and read the costs.

Nothing here talks to a model: the platform does, and its cost router enforces the budget. The
runner measures, and records whether any project went over its cap (the v0.3 criterion).
"""

from __future__ import annotations

import contextlib
import re
import shutil
import tempfile
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Protocol

from .api import ApiError, CobbleApi
from .hidden import HiddenError, HiddenResult, run_hidden
from .projects import ReferenceProject

SUCCESS = "success"
TESTS_FAILED = "tests_failed"
BUILD_FAILED = "build_failed"
BUDGET_PAUSED = "budget_paused"
TIMEOUT = "timeout"
ERROR = "error"
SKIPPED = "skipped"
OUTCOMES = (SUCCESS, TESTS_FAILED, BUILD_FAILED, BUDGET_PAUSED, TIMEOUT, ERROR, SKIPPED)

MESSAGE_LIMIT = 8000  # characters accepted by POST /projects/{id}/messages
SPEC_INTRO = {
    "en": "Here is the frozen specification. Use it as it is: do not add, remove or reinterpret features.",
    "fr": "Voici la spécification figée. Utilise-la telle quelle: n'ajoute, ne retire et ne réinterprète aucune fonctionnalité.",
}
SPEC_FEEDBACK = {
    "en": "Write the specification from the frozen text above, keeping every rule and every exact text.",
    "fr": "Rédige la spécification à partir du texte figé ci-dessus, en gardant chaque règle et chaque texte exact.",
}


def interview_message(project: ReferenceProject, lang: str) -> str:
    """What the 'user' says: the idea, then the frozen specification."""
    return f"{project.idea[lang]}\n\n{SPEC_INTRO[lang]}\n\n{project.spec(lang)}"


def money(value: Any) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return Decimal(0)


@dataclass
class ProjectResult:
    name: str
    outcome: str = SKIPPED
    detail: str = ""
    project_id: str | None = None
    cap_usd: Decimal = Decimal(0)
    spent_usd: Decimal = Decimal(0)
    estimate_usd: Decimal | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    calls: int = 0
    fallback_calls: int = 0
    escalated_tasks: int = 0
    attempts: int = 0
    tasks_total: int = 0
    tasks_merged: int = 0
    max_task_cost_usd: Decimal = Decimal(0)
    duration_s: float = 0.0
    hidden_passed: int = 0
    hidden_total: int = 0
    hidden_failed: list[str] = field(default_factory=list)
    by_model: dict[str, str] = field(default_factory=dict)

    @property
    def within_budget(self) -> bool:
        return self.outcome == SKIPPED or self.spent_usd <= self.cap_usd

    @property
    def success(self) -> bool:
        return self.outcome == SUCCESS


class Fetcher(Protocol):
    """Puts the generated project's files in `dest` and returns the project root."""

    def fetch(self, project: ReferenceProject, api_project: dict[str, Any], dest: Path) -> Path: ...


@dataclass
class BenchConfig:
    lang: str = "en"
    per_project_cap_usd: Decimal | None = None  # None: the project's own budget_usd
    total_budget_usd: Decimal = Decimal("8.00")
    timeout_scale: float = 1.0
    poll_s: float = 5.0
    step_timeout_s: float = 300.0  # for each planning step (reply, spec, plan)
    python: Sequence[str] | None = None  # interpreter that runs the hidden tests
    keep_workdirs: bool = False


class BenchRunner:
    def __init__(
        self,
        api: CobbleApi,
        fetcher: Fetcher,
        config: BenchConfig,
        *,
        run_label: str,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        log: Callable[[str], None] = lambda _: None,
        hidden_runner: Callable[..., HiddenResult] = run_hidden,
    ) -> None:
        self.api, self.fetcher, self.config = api, fetcher, config
        self.run_label = run_label
        self._sleep, self._clock, self._log = sleep, clock, log
        self._hidden = hidden_runner

    # --- public ------------------------------------------------------------------------------

    def run(self, projects: Sequence[ReferenceProject]) -> list[ProjectResult]:
        results: list[ProjectResult] = []
        spent = Decimal(0)
        for project in projects:
            remaining = self.config.total_budget_usd - spent
            cap = self.config.per_project_cap_usd or Decimal(str(project.budget_usd))
            result = ProjectResult(name=project.name, cap_usd=min(cap, max(remaining, Decimal(0))))
            if remaining <= 0:
                result.detail = "total_budget"
                results.append(result)
                self._log(f"[{project.name}] skipped: the total budget is used up")
                continue
            try:
                self._run_one(project, result)
            except ApiError as exc:
                result.outcome, result.detail = ERROR, f"api_{exc.status}"
                self._collect_quietly(result)
            except Exception as exc:
                result.outcome, result.detail = ERROR, type(exc).__name__
                self._collect_quietly(result)
            spent += result.spent_usd
            self._log(
                f"[{project.name}] {result.outcome} ${result.spent_usd} "
                f"(cap ${result.cap_usd}) {result.detail}".rstrip()
            )
            results.append(result)
        return results

    # --- one project -------------------------------------------------------------------------

    def _wait(self, what: str, until: Callable[[], Any], limit_s: float) -> Any:
        deadline = self._clock() + limit_s
        while True:
            found = until()
            if found:
                return found
            if self._clock() >= deadline:
                raise TimeoutError(what)
            self._sleep(self.config.poll_s)

    def _run_one(self, project: ReferenceProject, result: ProjectResult) -> None:
        api = self.api
        started = self._clock()
        pid = api.create_project(f"bench-{project.name}-{self.run_label}")
        result.project_id = pid
        api.set_budget(pid, f"{result.cap_usd:.2f}")
        try:
            self._plan(project, pid, result)
        except TimeoutError as exc:
            result.outcome, result.detail = TIMEOUT, f"planning:{exc}"
            self._collect(pid, result)
            result.duration_s = self._clock() - started
            return
        api.start(pid)
        self._log(f"[{project.name}] build started")
        outcome, detail = self._follow(project, pid, result, started)
        result.outcome, result.detail = outcome, detail
        self._collect(pid, result)
        if result.tasks_merged > 0:
            self._run_hidden(project, pid, result)
        if outcome == SUCCESS and not (
            result.hidden_total and result.hidden_passed == result.hidden_total
        ):
            result.outcome = TESTS_FAILED
        result.duration_s = self._clock() - started

    def _plan(self, project: ReferenceProject, pid: str, result: ProjectResult) -> None:
        lang, api, limit = self.config.lang, self.api, self.config.step_timeout_s
        text = interview_message(project, lang)
        if len(text) > MESSAGE_LIMIT:
            raise ValueError("interview message too long")
        before = len(api.messages(pid))
        api.post_message(pid, text)
        self._wait(
            "reply",
            lambda: (m := api.messages(pid)) and len(m) > before and m[-1]["role"] == "assistant",
            limit,
        )
        api.generate_spec(pid, SPEC_FEEDBACK[lang])
        self._wait("spec", lambda: api.spec(pid), limit)
        api.approve_spec(pid)
        api.generate_plan(pid, None)
        plan = self._wait("plan", lambda: api.plan(pid), limit)
        estimate = (plan.get("estimate") or {}).get("cost_usd")
        result.estimate_usd = money(estimate) if estimate is not None else None
        api.approve_plan(pid)

    def _follow(
        self, project: ReferenceProject, pid: str, result: ProjectResult, started: float
    ) -> tuple[str, str]:
        api = self.api
        deadline = self._clock() + project.timeout_s * self.config.timeout_scale
        validated: set[str] = set()
        while True:
            info = api.project(pid)
            tasks = api.tasks(pid)
            for milestone in api.milestones(pid):
                if milestone.get("status") == "built" and milestone["ref"] not in validated:
                    validated.add(milestone["ref"])
                    api.validate_milestone(pid, milestone["ref"])
                    self._log(f"[{project.name}] demo {milestone['ref']} validated")
            if info.get("phase") == "done":
                return SUCCESS, ""
            bad = [t["ref"] for t in tasks if t.get("state") in ("failed", "blocked")]
            if bad:
                return BUILD_FAILED, ",".join(bad[:5])
            if info.get("status") == "paused":
                return BUDGET_PAUSED, ""
            spent = money(api.costs(pid).get("spent_usd"))
            result.spent_usd = spent
            if spent > result.cap_usd:
                return BUDGET_PAUSED, "over_cap"
            if self._clock() >= deadline:
                return TIMEOUT, "building"
            self._sleep(self.config.poll_s)

    def _collect(self, pid: str, result: ProjectResult) -> None:
        costs = self.api.costs(pid)
        result.spent_usd = money(costs.get("spent_usd"))
        tokens = costs.get("tokens") or {}
        result.prompt_tokens = int(tokens.get("prompt", 0))
        result.completion_tokens = int(tokens.get("completion", 0))
        result.fallback_calls = int((costs.get("fallbacks") or {}).get("calls", 0))
        result.calls = sum(int(m.get("calls", 0)) for m in costs.get("by_model", []))
        result.by_model = {str(m["model"]): str(m["cost_usd"]) for m in costs.get("by_model", [])}
        per_task = [money(t.get("cost_usd")) for t in costs.get("by_task", []) if t.get("ref")]
        result.max_task_cost_usd = max(per_task, default=Decimal(0))
        tasks = self.api.tasks(pid)
        result.tasks_total = len(tasks)
        result.tasks_merged = sum(1 for t in tasks if t.get("state") == "merged")
        result.escalated_tasks = sum(1 for t in tasks if t.get("escalated"))
        result.attempts = sum(int(t.get("attempts", 0)) for t in tasks)

    def _collect_quietly(self, result: ProjectResult) -> None:
        """After a failure, still record what was spent: the budget criterion needs it."""
        if result.project_id is None:
            return
        with contextlib.suppress(Exception):  # best effort
            self._collect(result.project_id, result)

    def _run_hidden(self, project: ReferenceProject, pid: str, result: ProjectResult) -> None:
        work = Path(tempfile.mkdtemp(prefix=f"cobble-bench-{project.name}-"))
        try:
            code = self.fetcher.fetch(project, self.api.project(pid), work / "code")
            hidden = self._hidden(project, code, python=self.config.python)
        except (HiddenError, OSError, RuntimeError) as exc:
            result.detail = (result.detail + " " if result.detail else "") + f"hidden:{exc}"[:200]
            return
        finally:
            if not self.config.keep_workdirs:
                shutil.rmtree(work, ignore_errors=True)
        result.hidden_total, result.hidden_passed = hidden.total, hidden.passed
        result.hidden_failed = hidden.failed[:20]
        if hidden.error:
            result.detail = (
                result.detail + " " if result.detail else ""
            ) + f"hidden:{hidden.error}"


def slug(name: str) -> str:
    """Same rule as the platform's repository naming (`scheduler/engine.py: slug`)."""
    text = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return text[:40].strip("-") or "project"
