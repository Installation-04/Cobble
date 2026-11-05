"""An in-memory stand-in for a Cobble instance, for `--dry-run` and the runner's own tests.

It spends nothing and calls no model. The "generated code" it hands to the hidden tests is the
reference solution (optionally broken by the first mutation), so a dry run exercises the whole
pipeline: API calls, polling, budget bookkeeping, hidden tests, reports. The numbers it
produces are invented and the report says so: a dry run is never a measurement.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from .api import ApiError
from .projects import ReferenceProject
from .validate import build_tree


@dataclass
class Scenario:
    """How the fake build of one reference project goes."""

    ends: str = "done"  # done | failed | budget | overspend | never
    cost_usd: str = "0.12"
    prompt_tokens: int = 40_000
    completion_tokens: int = 9_000
    polls_to_finish: int = 2
    fallback_calls: int = 0
    escalated_tasks: int = 0
    broken_code: bool = False  # hand the hidden tests a solution with its first mutation applied


class FakeCobble:
    def __init__(self, scenarios: dict[str, Scenario] | None = None) -> None:
        self.scenarios = scenarios or {}
        self.logged_in = False
        self.preset: tuple[str, dict[str, str]] | None = None
        self.models: dict[str, Any] = {
            "effective": {"planner": ["sim-model"]},
            "default": "sim-model",
            "models": ["sim-model"],
        }
        self.calls: list[str] = []
        self._ids = itertools.count(1)
        self._projects: dict[str, dict[str, Any]] = {}

    # --- helpers -----------------------------------------------------------------------------

    def scenario_of(self, project_id: str) -> Scenario:
        name = self._projects[project_id]["name"]
        for key, scenario in self.scenarios.items():
            if f"bench-{key}-" in name:
                return scenario
        return Scenario()

    def _get(self, project_id: str) -> dict[str, Any]:
        if project_id not in self._projects:
            raise ApiError(404)
        return self._projects[project_id]

    # --- CobbleApi ---------------------------------------------------------------------------

    def login(self, email: str, password: str) -> None:
        self.logged_in = True

    def model_setup(self) -> dict[str, Any]:
        return self.models

    def apply_preset(self, preset_id: str, slots: dict[str, str]) -> None:
        self.preset = (preset_id, slots)

    def create_project(self, name: str) -> str:
        pid = f"p{next(self._ids)}"
        self._projects[pid] = {
            "name": name, "budget": None, "phase": "interview", "status": "active",
            "messages": [], "spec": None, "plan": None, "polls": 0, "validated": set(),
        }  # fmt: skip
        self.calls.append(f"create:{name}")
        return pid

    def set_budget(self, project_id: str, budget_usd: str) -> None:
        self._get(project_id)["budget"] = Decimal(budget_usd)

    def project(self, project_id: str) -> dict[str, Any]:
        state = self._get(project_id)
        if state["phase"] == "building":
            state["polls"] += 1
            scenario = self.scenario_of(project_id)
            if state["polls"] >= scenario.polls_to_finish:
                if scenario.ends == "done":
                    state["phase"] = "done"
                elif scenario.ends == "budget":
                    state["status"] = "paused"
        return {"id": project_id, "phase": state["phase"], "status": state["status"],
                "budget_usd": str(state["budget"]), "name": state["name"]}  # fmt: skip

    def messages(self, project_id: str) -> list[dict[str, Any]]:
        return list(self._get(project_id)["messages"])

    def post_message(self, project_id: str, content: str) -> None:
        messages = self._get(project_id)["messages"]
        messages.append({"role": "user", "content": content})
        messages.append({"role": "assistant", "content": "ok"})

    def generate_spec(self, project_id: str, feedback: str | None) -> None:
        state = self._get(project_id)
        state["spec"], state["phase"] = {"version": 1, "status": "draft"}, "spec_review"

    def spec(self, project_id: str) -> dict[str, Any] | None:
        return self._get(project_id)["spec"]

    def approve_spec(self, project_id: str) -> None:
        self._get(project_id)["spec"]["status"] = "approved"

    def generate_plan(self, project_id: str, feedback: str | None) -> None:
        state = self._get(project_id)
        state["plan"], state["phase"] = (
            {"version": 1, "estimate": {"cost_usd": "0.50"}},
            "plan_review",
        )

    def plan(self, project_id: str) -> dict[str, Any] | None:
        return self._get(project_id)["plan"]

    def approve_plan(self, project_id: str) -> None:
        self._get(project_id)["phase"] = "ready"

    def start(self, project_id: str) -> None:
        self._get(project_id)["phase"] = "building"

    def tasks(self, project_id: str) -> list[dict[str, Any]]:
        scenario, state = self.scenario_of(project_id), self._get(project_id)
        done = state["phase"] == "done"
        states = ["merged", "merged", "merged" if done else "implementing"]
        if scenario.ends == "failed" and state["polls"] >= scenario.polls_to_finish:
            states[-1] = "failed"
        return [
            {"ref": f"T-00{i + 1}", "state": s, "escalated": i < scenario.escalated_tasks,
             "attempts": 1 + int(i < scenario.escalated_tasks)}
            for i, s in enumerate(states)
        ]  # fmt: skip

    def milestones(self, project_id: str) -> list[dict[str, Any]]:
        state = self._get(project_id)
        if state["phase"] not in ("building", "done"):
            return []
        status = "validated" if "M1" in state["validated"] else "built"
        return [{"ref": "M1", "status": status}]

    def validate_milestone(self, project_id: str, ref: str) -> None:
        self._get(project_id)["validated"].add(ref)

    def costs(self, project_id: str) -> dict[str, Any]:
        state, scenario = self._get(project_id), self.scenario_of(project_id)
        spent = Decimal(0)
        if state["phase"] in ("building", "done") and state["polls"] >= 1:
            spent = Decimal(scenario.cost_usd)
        if scenario.ends == "budget":
            spent = state["budget"] or Decimal(0)
        if scenario.ends == "overspend" and state["polls"] >= 1:
            spent = (state["budget"] or Decimal(0)) + Decimal("0.50")
        return {
            "budget_usd": str(state["budget"]),
            "spent_usd": f"{spent:.2f}",
            "tokens": {"prompt": scenario.prompt_tokens if spent else 0,
                       "completion": scenario.completion_tokens if spent else 0},
            "by_task": [{"ref": "T-001", "cost_usd": f"{spent / 3:.2f}", "calls": 3}],
            "by_model": [{"model": "sim-model", "cost_usd": f"{spent:.2f}", "calls": 12 if spent else 0}],
            "fallbacks": {"calls": scenario.fallback_calls, "total_calls": 12, "by_model": []},
        }  # fmt: skip


class SolutionFetcher:
    """Hands out the reference solution (laid over the template) as the 'generated code'."""

    def __init__(self, cobble: FakeCobble, *, broken: bool = False) -> None:
        self.cobble = cobble
        self.broken = broken

    def fetch(self, project: ReferenceProject, api_project: dict[str, Any], dest: Path) -> Path:
        build_tree(project, dest)
        scenario = self.cobble.scenario_of(api_project["id"])
        if self.broken or scenario.broken_code:
            mutation = project.mutations()[0]
            target = dest / mutation.file
            target.write_text(
                target.read_text("utf-8").replace(mutation.old, mutation.new), "utf-8"
            )
        return dest
