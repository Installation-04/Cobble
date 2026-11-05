"""Prove that a hidden suite is satisfiable and discriminating, without any model.

1. The reference solution (laid over the template) must pass every hidden test.
2. Each mutation of `mutations.json` (a deliberate breakage of the solution) must make at
   least one hidden test fail, and the base template alone (no solution) must fail too.
"""

from __future__ import annotations

import shutil
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from .hidden import HiddenResult, run_hidden
from .projects import TEMPLATE_DIR, ReferenceProject

SKIP_DIRS = {".venv", "node_modules", "dist", "__pycache__", ".pytest_cache", ".ruff_cache"}


def build_tree(project: ReferenceProject, target: Path, *, with_solution: bool = True) -> None:
    """The template, then (optionally) the reference solution laid over it."""

    def ignore(_: str, names: list[str]) -> set[str]:
        return {n for n in names if n in SKIP_DIRS}

    shutil.copytree(TEMPLATE_DIR, target, ignore=ignore, dirs_exist_ok=True)
    for path in target.rglob("*"):
        if path.is_file() and path.suffix in {".py", ".md", ".ts", ".tsx", ".json", ".html"}:
            text = path.read_text("utf-8")
            if "{{project_name}}" in text:
                path.write_text(text.replace("{{project_name}}", project.title["en"]), "utf-8")
    if with_solution:
        shutil.copytree(project.solution_tree, target, ignore=ignore, dirs_exist_ok=True)


@dataclass
class MutationOutcome:
    name: str
    caught: bool
    failed_tests: list[str] = field(default_factory=list)
    problem: str | None = None


@dataclass
class Validation:
    project: str
    solution: HiddenResult
    empty_template: HiddenResult
    mutations: list[MutationOutcome]

    @property
    def ok(self) -> bool:
        return (
            self.solution.ok
            and not self.empty_template.ok
            and bool(self.mutations)
            and all(m.caught for m in self.mutations)
        )


def validate(project: ReferenceProject, python: Sequence[str] | None = None) -> Validation:
    with tempfile.TemporaryDirectory(prefix="cobble-bench-solution-") as tmp:
        root = Path(tmp)
        good = root / "solution"
        build_tree(project, good)
        solution = run_hidden(project, good, python=python)

        empty = root / "template"
        build_tree(project, empty, with_solution=False)
        empty_result = run_hidden(project, empty, python=python)

        outcomes: list[MutationOutcome] = []
        for index, mutation in enumerate(project.mutations()):
            broken = root / f"mutant-{index}"
            build_tree(project, broken)
            target = broken / mutation.file
            if not target.is_file():
                outcomes.append(MutationOutcome(mutation.name, False, problem="missing file"))
                continue
            text = target.read_text("utf-8")
            if text.count(mutation.old) != 1:
                outcomes.append(
                    MutationOutcome(mutation.name, False, problem="old text not found once")
                )
                continue
            target.write_text(text.replace(mutation.old, mutation.new), "utf-8")
            result = run_hidden(project, broken, python=python)
            outcomes.append(MutationOutcome(mutation.name, not result.ok, result.failed[:5]))
            shutil.rmtree(broken, ignore_errors=True)
    return Validation(project.name, solution, empty_result, outcomes)
