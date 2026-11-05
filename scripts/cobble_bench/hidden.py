"""Run the hidden acceptance tests of a reference project against a generated code tree.

The tests are copied (with the shared conftest) into a temporary directory OUTSIDE the code
tree, and pytest runs from there with the code tree on `sys.path`. They are never written
inside the generated repository, so an agent can neither read nor edit them. `assert_unreachable`
is the guard the runner and the unit tests rely on.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from .projects import COMMON_DIR, ReferenceProject

DEFAULT_TIMEOUT_S = 300


class HiddenError(Exception):
    """The hidden tests could not be run (not the same as: they failed)."""


@dataclass
class HiddenResult:
    total: int = 0
    passed: int = 0
    failed: list[str] = field(default_factory=list)
    error: str | None = None  # the suite could not run at all (import error, timeout...)
    output_tail: str = ""

    @property
    def ok(self) -> bool:
        return (
            self.error is None and self.total > 0 and not self.failed and self.passed == self.total
        )

    @property
    def score(self) -> float:
        return self.passed / self.total if self.total else 0.0


def default_python() -> list[str]:
    """The interpreter that runs the tests: `BENCH_PYTHON` (a command line) or this one.

    It must be able to import fastapi, httpx and pytest, plus whatever the project needs (the
    generated project's own dependencies). The real bench uses `uv run --project {code} python`
    (`{code}` is replaced by the project root), which builds an environment from the project's
    own `uv.lock`.
    """
    configured = os.environ.get("BENCH_PYTHON", "").split()
    return configured or [sys.executable]


def assert_unreachable(project: ReferenceProject, code_dir: Path) -> None:
    """Raise when the hidden tests live inside `code_dir` (or the code is inside the tests)."""
    code = code_dir.resolve()
    for secret in (project.hidden_dir.resolve(), COMMON_DIR.resolve()):
        if secret == code or secret in code.parents or code in secret.parents:
            raise HiddenError(f"hidden tests are reachable from the code tree: {secret}")
    secrets = {p.name: p.read_bytes() for p in project.hidden_dir.glob("*.py")}
    for path in code.rglob("*.py"):
        if "node_modules" in path.parts or path.name not in secrets:
            continue
        if path.read_bytes() == secrets[path.name]:
            raise HiddenError(f"a hidden test file leaked into the code tree: {path}")


def _parse_junit(xml_file: Path) -> tuple[int, int, list[str]]:
    root = ET.parse(xml_file).getroot()  # noqa: S314 - written by our own pytest run
    total = passed = 0
    failed: list[str] = []
    for case in root.iter("testcase"):
        total += 1
        if case.find("failure") is not None or case.find("error") is not None:
            failed.append(f"{case.get('classname', '')}::{case.get('name', '')}".strip(":"))
        elif case.find("skipped") is not None:
            failed.append(f"{case.get('name', '')} (skipped)")
        else:
            passed += 1
    return total, passed, failed


def run_hidden(
    project: ReferenceProject,
    code_dir: Path,
    *,
    python: Sequence[str] | None = None,
    timeout_s: int = DEFAULT_TIMEOUT_S,
) -> HiddenResult:
    """Run the suite. `code_dir` is the root of the generated project (it holds `app/`)."""
    assert_unreachable(project, code_dir)
    if not project.hidden_dir.is_dir():
        raise HiddenError(f"{project.name}: no hidden tests")
    with tempfile.TemporaryDirectory(prefix="cobble-bench-hidden-") as tmp:
        work = Path(tmp)
        suite = work / "suite"
        shutil.copytree(project.hidden_dir, suite)
        shutil.copy2(COMMON_DIR / "conftest.py", suite / "conftest.py")
        report = work / "report.xml"
        env = {k: v for k, v in os.environ.items() if k != "VIRTUAL_ENV"}
        env.update(
            BENCH_PROJECT_DIR=str(code_dir.resolve()),
            PYTHONDONTWRITEBYTECODE="1",
            PYTHONPATH="",
        )
        interpreter = [
            part.replace("{code}", str(code_dir.resolve())) for part in python or default_python()
        ]
        cmd = [
            *interpreter,
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            f"--junitxml={report}",
            str(suite),
        ]
        try:
            done = subprocess.run(  # noqa: S603
                cmd,
                cwd=work,
                env=env,
                capture_output=True,
                text=True,
                timeout=timeout_s,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return HiddenResult(error="timeout")
        except FileNotFoundError as exc:
            raise HiddenError(f"cannot start the test interpreter: {exc}") from exc
        tail = "\n".join((done.stdout + done.stderr).strip().splitlines()[-25:])
        if not report.is_file():
            return HiddenResult(error="no_report", output_tail=tail)
        total, passed, failed = _parse_junit(report)
        if total == 0:  # collection error: the application could not even be imported
            return HiddenResult(error="collection_failed", output_tail=tail)
        return HiddenResult(total=total, passed=passed, failed=failed, output_tail=tail)
