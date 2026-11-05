"""The reference projects on disk: specs, hidden tests, reference solutions, mutations.

Layout of `reference-projects/<name>/`:

    project.json    name, one-line idea (fr, en), budget and time caps, what the project measures
    spec.md         the frozen specification (English); spec.fr.md is the French one
    hidden/         the hidden acceptance tests (pytest); never copied into a generated repository
    solution/tree/  a reference solution: files laid over the template (known to pass the tests)
    mutations.json  deliberate breakages of the solution; each one must make a hidden test fail

`reference-projects/_common/conftest.py` holds the fixtures shared by every hidden suite.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
PROJECTS_DIR = ROOT / "reference-projects"
COMMON_DIR = PROJECTS_DIR / "_common"
TEMPLATE_DIR = ROOT / "templates" / "fastapi-react"
LANGS = ("fr", "en")


class ProjectError(Exception):
    """A reference project is malformed or missing."""


@dataclass(frozen=True)
class Mutation:
    name: str
    file: str
    old: str
    new: str


@dataclass(frozen=True)
class ReferenceProject:
    name: str
    path: Path
    config: dict[str, Any]

    @property
    def title(self) -> dict[str, str]:
        return dict(self.config["title"])

    @property
    def idea(self) -> dict[str, str]:
        return dict(self.config["idea"])

    @property
    def budget_usd(self) -> float:
        return float(self.config["budget_usd"])

    @property
    def timeout_s(self) -> int:
        return int(self.config["timeout_s"])

    @property
    def hidden_dir(self) -> Path:
        return self.path / "hidden"

    @property
    def solution_tree(self) -> Path:
        return self.path / "solution" / "tree"

    def spec(self, lang: str) -> str:
        """The frozen specification. English is `spec.md`, French `spec.fr.md`."""
        name = "spec.fr.md" if lang == "fr" else "spec.md"
        return (self.path / name).read_text("utf-8")

    def mutations(self) -> list[Mutation]:
        file = self.path / "mutations.json"
        if not file.is_file():
            return []
        return [Mutation(**item) for item in json.loads(file.read_text("utf-8"))]


def names() -> list[str]:
    """Every reference project, sorted. A folder counts when it has a `project.json`."""
    if not PROJECTS_DIR.is_dir():
        return []
    return sorted(p.name for p in PROJECTS_DIR.iterdir() if (p / "project.json").is_file())


def load(name: str, base: Path = PROJECTS_DIR) -> ReferenceProject:
    path = base / name
    file = path / "project.json"
    if not file.is_file():
        raise ProjectError(f"unknown reference project: {name}")
    config = json.loads(file.read_text("utf-8"))
    for key in ("title", "idea", "budget_usd", "timeout_s"):
        if key not in config:
            raise ProjectError(f"{name}/project.json: missing '{key}'")
    for key in ("title", "idea"):
        if set(config[key]) != set(LANGS):
            raise ProjectError(f"{name}/project.json: '{key}' needs fr and en")
    return ReferenceProject(name=name, path=path, config=config)


def load_all(
    selected: list[str] | None = None, base: Path = PROJECTS_DIR
) -> list[ReferenceProject]:
    wanted = selected or names()
    return [load(name, base) for name in wanted]
