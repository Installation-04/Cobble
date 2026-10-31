#!/usr/bin/env python3
"""Dry run of the to-do reference solution against the template's CI (no agent, no model).

Copies `templates/fastapi-react` into a temporary directory, renders the project name, then
applies the solution task by task in a dependency-respecting order, exactly as the chain
would: first the test files of the task (they must FAIL: tests come first), then the other
files. After each task it runs the checks of the template's `.woodpecker.yaml` that work
locally:

    ruff check, ruff format --check, pytest            (every task)
    pnpm test, pnpm build                              (tasks that touch frontend/)
    python -m app.seed and TODO_SEED=1 start-up        (DEMO tasks)

and prints a PASS/FAIL table. `--orders N` repeats the run with N more random orders (the
property to check: ANY order that respects depends_on stays green). `--scanners` also runs
Semgrep, Trivy and Gitleaks on the final tree with the images pinned in `.woodpecker.yaml`
(needs Docker and network access to the registries).

    python3 scripts/verify_solution.py [--orders 2] [--scanners] [--keep] [--no-frontend]
"""

from __future__ import annotations

import argparse
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import make_agent_cassettes as agents

ROOT = agents.ROOT
PROJECT_NAME = "Todo list"
SKIP_DIRS = {".venv", "node_modules", "dist", "__pycache__", ".pytest_cache", ".ruff_cache"}


@dataclass
class Result:
    ref: str
    cells: dict[str, str] = field(default_factory=dict)
    log: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(value in ("PASS", "-") for value in self.cells.values())


def run(
    cmd: list[str], cwd: Path, env: dict[str, str] | None = None, timeout: int = 600
) -> tuple[bool, str]:
    merged = {k: v for k, v in os.environ.items() if k != "VIRTUAL_ENV"}
    merged.update(env or {})
    try:
        done = subprocess.run(  # noqa: S603
            cmd, cwd=cwd, env=merged, capture_output=True, text=True, timeout=timeout, check=False
        )
    except FileNotFoundError as exc:
        return False, str(exc)
    except subprocess.TimeoutExpired:
        return False, f"timeout after {timeout}s: {' '.join(cmd)}"
    return done.returncode == 0, (done.stdout + done.stderr).strip()


def render_template(target: Path) -> None:
    def ignore(_: str, names: list[str]) -> set[str]:
        return {n for n in names if n in SKIP_DIRS}

    shutil.copytree(agents.TEMPLATE, target, ignore=ignore, dirs_exist_ok=True)
    for path in target.rglob("*"):
        if path.is_file() and path.suffix in {".py", ".html", ".md", ".ts", ".tsx", ".json"}:
            text = path.read_text("utf-8")
            if "{{project_name}}" in text:
                path.write_text(text.replace("{{project_name}}", PROJECT_NAME), encoding="utf-8")


def write_files(root: Path, files: dict[str, str]) -> None:
    for path, text in files.items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")


def local_tests(root: Path, tests: str) -> tuple[bool, str]:
    """The task's own test command (cobble/scheduler/prompts.py: local_test_command)."""
    if tests.endswith(".py"):
        return run(["uv", "run", "pytest", "-q", tests], root)
    return run(["pnpm", "--dir", "frontend", "test"], root)


def tail(text: str, lines: int = 25) -> str:
    return "\n".join(text.splitlines()[-lines:])


def check_step(
    root: Path,
    step: agents.Step,
    files: dict[str, str],
    tests_field: str,
    frontend: bool,
    seed_smoke: bool,
) -> Result:
    result = Result(step.ref)
    tests = {p: t for p, t in files.items() if agents.is_test_file(p)}
    rest = {p: t for p, t in files.items() if not agents.is_test_file(p)}

    def record(column: str, ok: bool, output: str) -> None:
        result.cells[column] = "PASS" if ok else "FAIL"
        if not ok:
            result.log.append(f"[{step.ref}] {column}:\n{tail(output)}")

    if step.writer and tests_field:
        write_files(root, tests)
        ok, out = local_tests(root, tests_field)
        result.cells["red"] = "PASS" if not ok else "FAIL"  # tests first: they must fail
        if ok:
            result.log.append(
                f"[{step.ref}] red: the new tests already pass before the code\n{tail(out)}"
            )
    else:
        result.cells["red"] = "-"
    write_files(root, rest if step.writer else files)
    if step.writer and tests_field:
        ok, out = local_tests(root, tests_field)
        record("green", ok, out)
    else:
        result.cells["green"] = "-"
    ok, out = run(["uv", "run", "ruff", "check", "."], root)
    record("ruff", ok, out)
    ok, out = run(["uv", "run", "ruff", "format", "--check", "."], root)
    record("format", ok, out)
    ok, out = run(["uv", "run", "pytest", "-q"], root)
    record("pytest", ok, out)
    touches_frontend = any(p.startswith("frontend/") for p in step.files)
    if frontend and touches_frontend:
        ok, out = run(["pnpm", "test"], root / "frontend")
        record("vitest", ok, out)
        ok, out = run(["pnpm", "build"], root / "frontend")
        record("build", ok, out)
    else:
        result.cells["vitest"] = result.cells["build"] = "-"
    if seed_smoke and step.kind == "demo":
        env = {"TODO_DB": str(root / "seed-smoke.db")}
        (root / "seed-smoke.db").unlink(missing_ok=True)
        ok, out = run(["uv", "run", "python", "-m", "app.seed"], root, env)
        found = re.search(r"(\d+) demo todos added", out)
        ok = ok and found is not None and int(found.group(1)) >= 6
        record("seed", ok, out)
        code = (
            "from fastapi.testclient import TestClient\n"
            "from app.main import app\n"
            "with TestClient(app) as c:\n"
            "    n = len(c.get('/api/todos').json())\n"
            "    assert n >= 6, n\n"
        )
        ok, out = run(["uv", "run", "python", "-c", code], root, {**env, "TODO_SEED": "1"})
        (root / "seed-smoke.db").unlink(missing_ok=True)
        record("TODO_SEED", ok, out)
    return result


def prepare(root: Path, frontend: bool) -> None:
    render_template(root)
    ok, out = run(["uv", "sync", "--locked"], root)
    if not ok:
        raise SystemExit(f"uv sync failed:\n{tail(out)}")
    if frontend:
        ok, out = run(["pnpm", "install", "--frozen-lockfile", "--offline"], root / "frontend")
        if not ok:
            ok, out = run(["pnpm", "install", "--frozen-lockfile"], root / "frontend")
        if not ok:
            raise SystemExit(f"pnpm install failed:\n{tail(out)}")


def verify_order(
    order: list[agents.Step],
    contents: dict[str, dict[str, str]],
    tests_of: dict[str, str],
    frontend: bool,
    keep: bool,
    label: str,
) -> list[Result]:
    workdir = Path(tempfile.mkdtemp(prefix="cobble-solution-"))
    root = workdir / "project"
    results: list[Result] = []
    try:
        prepare(root, frontend)
        print(f"\n== {label}: {' '.join(s.ref for s in order)}", flush=True)
        for step in order:
            started = time.monotonic()
            result = check_step(
                root, step, contents[step.ref], tests_of.get(step.ref, ""), frontend, True
            )
            results.append(result)
            print(
                f"   {step.ref:<8} {'PASS' if result.ok else 'FAIL'} "
                f"({time.monotonic() - started:.0f}s)",
                flush=True,
            )
            if not result.ok:
                break
        else:
            compare_tree(root, label, results)
    finally:
        if keep:
            print(f"kept {workdir}")
        else:
            shutil.rmtree(workdir, ignore_errors=True)
    return results


def compare_tree(root: Path, label: str, results: list[Result]) -> None:
    """After all tasks the repository holds solution/tree (C-001 and seed.py aside)."""
    expected = {
        p.relative_to(agents.TREE_DIR).as_posix(): p.read_text("utf-8")
        for p in agents.TREE_DIR.rglob("*")
        if p.is_file()
    }
    differences = [
        path
        for path, text in expected.items()
        if (root / path).read_text("utf-8") != text
        and path not in agents.COMMENT_FILES  # C-001 rewrites these on top of the finished app
    ]
    cell = "PASS" if not differences else "FAIL"
    final = Result(f"tree ({label})", {"tree": cell})
    if differences:
        final.log.append("files that differ from solution/tree: " + ", ".join(differences))
    results.append(final)


def print_table(results: list[Result]) -> None:
    columns = [
        "red",
        "green",
        "ruff",
        "format",
        "pytest",
        "vitest",
        "build",
        "seed",
        "TODO_SEED",
        "tree",
    ]
    columns = [c for c in columns if any(c in r.cells for r in results)]
    print("\n| Task | " + " | ".join(columns) + " |")
    print("|---|" + "---|" * len(columns))
    for r in results:
        print(f"| {r.ref} | " + " | ".join(r.cells.get(c, "") or "-" for c in columns) + " |")


def run_scanners(root_tree: Path) -> list[str]:
    """Semgrep, Trivy and Gitleaks as in .woodpecker.yaml, through Docker. Returns failures."""
    ci = (agents.TEMPLATE / ".woodpecker.yaml").read_text("utf-8")
    images = {
        name: re.search(rf"image: ({name}[^\s]*)", ci).group(1)  # type: ignore[union-attr]
        for name in ("semgrep/semgrep", "aquasec/trivy", "zricethezav/gitleaks")
    }
    commands = {
        "semgrep": [
            images["semgrep/semgrep"],
            "semgrep",
            "scan",
            "--config",
            "p/default",
            "--metrics",
            "off",
            "--severity",
            "ERROR",
            "--error",
            "--exclude",
            "node_modules",
            "--exclude",
            ".venv",
            ".",
        ],
        "trivy": [
            images["aquasec/trivy"],
            "fs",
            "--scanners",
            "vuln",
            "--severity",
            "HIGH,CRITICAL",
            "--ignore-unfixed",
            "--exit-code",
            "1",
            "--no-progress",
            "--skip-dirs",
            "node_modules",
            "--skip-dirs",
            ".venv",
            ".",
        ],
        "gitleaks": [
            images["zricethezav/gitleaks"],
            "dir",
            ".",
            "--no-banner",
            "--redact",
            "--exit-code",
            "1",
        ],
    }
    failures: list[str] = []
    if not run(["docker", "info"], root_tree, timeout=30)[0]:
        print("   docker is not reachable: scanners NOT run")
        return failures
    ca = "/root/.ccr/ca-bundle.crt"
    for name, cmd in commands.items():
        docker = ["docker", "run", "--rm", "-v", f"{root_tree}:/src:ro", "-w", "/src"]
        if Path(ca).is_file():
            docker += [
                "-v",
                f"{ca}:/ca.crt:ro",
                "-e",
                "SSL_CERT_FILE=/ca.crt",
                "-e",
                "REQUESTS_CA_BUNDLE=/ca.crt",
            ]
        ok, out = run([*docker, *cmd], root_tree, timeout=900)
        print(f"   {name:<9} {'PASS' if ok else 'FAIL'}", flush=True)
        if not ok:
            failures.append(f"{name}:\n{tail(out, 40)}")
    return failures


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--orders", type=int, default=0, help="extra random dependency orders")
    parser.add_argument("--seed", type=int, default=7, help="seed of the random orders")
    parser.add_argument("--scanners", action="store_true", help="run semgrep, trivy, gitleaks")
    parser.add_argument("--keep", action="store_true", help="keep the temporary directories")
    parser.add_argument("--no-frontend", action="store_true", help="skip pnpm steps")
    args = parser.parse_args(argv)
    try:
        steps = agents.load_steps()
        agents.check_shared_files(steps)
        contents = agents.read_tasks(steps)
    except agents.SolutionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    tests_of = {t["id"]: t["tests"] for t in agents.load_plan()["tasks"]}
    tests_of["C-001"] = "tests/test_c_001.py"
    frontend = not args.no_frontend
    plain = [s for s in steps if s.kind != "comment"]
    comment = [s for s in steps if s.kind == "comment"]
    rng = random.Random(args.seed)  # noqa: S311
    orders: list[tuple[str, list[agents.Step]]] = [
        ("default order", agents.ordered(plain) + comment)
    ]
    refs = [s.ref for s in plain]
    for n in range(args.orders):
        prefer = refs[:]
        rng.shuffle(prefer)
        orders.append((f"random order {n + 1}", agents.ordered(plain, prefer) + comment))
    failed = False
    first: list[Result] = []
    for label, order in orders:
        results = verify_order(order, contents, tests_of, frontend, args.keep, label)
        if not first:
            first = results
        failed = failed or not all(r.ok for r in results) or len(results) < len(order)
        for r in results:
            for chunk in r.log:
                print(chunk, file=sys.stderr)
    print_table(first)
    if args.scanners:
        print("\n== scanners (final tree)")
        workdir = Path(tempfile.mkdtemp(prefix="cobble-scan-"))
        try:
            render_template(workdir)
            write_files(
                workdir,
                {
                    p.relative_to(agents.TREE_DIR).as_posix(): p.read_text("utf-8")
                    for p in agents.TREE_DIR.rglob("*")
                    if p.is_file()
                },
            )
            for chunk in run_scanners(workdir):
                failed = True
                print(chunk, file=sys.stderr)
        finally:
            shutil.rmtree(workdir, ignore_errors=True)
    print("\nRESULT:", "FAIL" if failed else "PASS")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
