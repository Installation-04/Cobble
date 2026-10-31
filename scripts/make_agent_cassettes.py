#!/usr/bin/env python3
"""Write the agent cassettes of the to-do reference project (`agent-todo-*.json`).

The coding agent (Aider, "whole" edit format) is replayed by the fake LLM: a *marker* cassette
answers every request that contains `[cobble-task:<ref>:<role>:<attempt>]` with the complete
files of that step. The files come from the reference solution:

    reference-projects/todo/solution/tasks/<REF>/<path>   exact full content, per task (source)
    reference-projects/todo/solution/tree/<path>          the app after every task (generated)

The plan (tasks, files, dependencies) is read from the scripted planner answer
`providers/fake-llm/cassettes/todo-en-plan.json`, so the solution always follows the plan that
the build is launched from. Per task there are two steps, like in the real chain:

  * `test-writer` attempt 1 writes the test files of the task (`tests/**`, `*.test.ts[x]`),
  * `worker` attempt 1 writes the other files.

`DEMO-Mx` tasks (ADR 0007) only have a worker step (`app/seed.py`). `C-001` is a sample comment
task ("show a due date"), applied on top of the finished app. `X-LOOP` is a fictional task whose
worker answer is wrong on purpose (see LOOP_* below): Aider reruns the tests, sees the same
failure and the runner ends the run with `loop_detected`.

Usage (stdlib only, from the repository root):

    python3 scripts/make_agent_cassettes.py          # rewrite the tree and the cassettes
    python3 scripts/make_agent_cassettes.py --check  # exit 1 when something is out of date
    python3 scripts/make_agent_cassettes.py --table  # plan table (task, files, dependencies)

Aider 0.86 whole format: the line before a fence is the file path; the fence is "```" unless a
file in the chat has a line starting with it, in which case Aider picks a longer one (see
`choose_fence`). The answer must use the fence that Aider will pick, so it is computed from the
files in the chat (the task's files as they are at that point). `check` replays Aider's parser
on every answer and compares the result with the solution.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CASSETTES = ROOT / "providers" / "fake-llm" / "cassettes"
TEMPLATE = ROOT / "templates" / "fastapi-react"
SOLUTION = ROOT / "reference-projects" / "todo" / "solution"
TASKS_DIR = SOLUTION / "tasks"
TREE_DIR = SOLUTION / "tree"
PLAN_CASSETTE = CASSETTES / "todo-en-plan.json"
PREFIX = "agent-todo-"

TEST_WRITER = "test-writer"
WORKER = "worker"

# Files that several DEMO tasks write in full: any order gives a valid app (the last one wins).
SHARED_BY_DEMOS = frozenset({"app/seed.py"})

COMMENT_FILES = (
    "app/models.py",
    "app/db.py",
    "app/api/todos.py",
    "app/seed.py",
    "frontend/src/api.ts",
    "frontend/src/AddTodo.tsx",
    "frontend/src/TodoList.tsx",
    "frontend/src/App.tsx",
    "tests/test_c_001.py",
    "frontend/src/due.test.tsx",
)

# X-LOOP: the tests ask for add(2, 3) == 5, every worker attempt answers a - b. The test run
# fails with the same fingerprint again and again, which agent-service reports as loop_detected.
LOOP_REF = "X-LOOP"
LOOP_WORKER_ATTEMPTS = 4  # COBBLE_MAX_ATTEMPTS default: every attempt loops
LOOP_TEST = """from app.loop_demo import add


def test_add_sums_two_numbers() -> None:
    assert add(2, 3) == 5
"""
LOOP_CODE = """def add(a: int, b: int) -> int:
    return a - b
"""
LOOP_TEST_PATH = "tests/test_loop_demo.py"
LOOP_CODE_PATH = "app/loop_demo.py"


class SolutionError(Exception):
    """The plan, the solution and the cassettes are not consistent."""


@dataclass(frozen=True)
class Step:
    ref: str
    title: str
    milestone: str
    depends_on: tuple[str, ...]
    files: tuple[str, ...]
    kind: str  # "plan" | "demo" | "comment"
    writer: bool  # has a test-writer step


def is_test_file(path: str) -> bool:
    return path.startswith("tests/") or re.search(r"\.test\.(ts|tsx|js)$", path) is not None


def load_plan() -> dict[str, Any]:
    cassette = json.loads(PLAN_CASSETTE.read_text("utf-8"))
    plan = json.loads(cassette["response"]["content"])
    if not isinstance(plan, dict):
        raise SolutionError(f"{PLAN_CASSETTE.name}: the plan is not an object")
    return plan


def load_steps() -> list[Step]:
    """Plan tasks, then one DEMO task per milestone, then the sample comment task."""
    plan = load_plan()
    steps: list[Step] = []
    for task in plan["tasks"]:
        steps.append(
            Step(
                ref=task["id"],
                title=task["title"],
                milestone=task["milestone"],
                depends_on=tuple(task["depends_on"]),
                files=tuple(task["files"]),
                kind="plan",
                writer=True,
            )
        )
        if task["tests"] not in task["files"]:
            raise SolutionError(f"{task['id']}: `tests` must be one of its files")
    for milestone in plan["milestones"]:
        mid = milestone["id"]
        members = tuple(s.ref for s in steps if s.kind == "plan" and s.milestone == mid)
        steps.append(
            Step(
                ref=f"DEMO-{mid}",
                title=f"Generate realistic demo data ({mid})",
                milestone=mid,
                depends_on=members,
                files=("app/seed.py",),
                kind="demo",
                writer=False,
            )
        )
    everything = tuple(s.ref for s in steps)
    last_milestone = plan["milestones"][-1]["id"]
    steps.append(
        Step(
            ref="C-001",
            title="Show a due date on each task",
            milestone=last_milestone,
            depends_on=everything,
            files=COMMENT_FILES,
            kind="comment",
            writer=True,
        )
    )
    return steps


def ordered(steps: list[Step], prefer: Iterable[str] | None = None) -> list[Step]:
    """A dependency-respecting order; ties go to the earliest in `prefer` (default: list order)."""
    rank = {ref: i for i, ref in enumerate(prefer or [s.ref for s in steps])}
    by_ref = {s.ref: s for s in steps}
    for step in steps:
        for dep in step.depends_on:
            if dep not in by_ref:
                raise SolutionError(f"{step.ref}: unknown dependency {dep}")
    done: set[str] = set()
    result: list[Step] = []
    while len(result) < len(steps):
        ready = [s for s in steps if s.ref not in done and all(d in done for d in s.depends_on)]
        if not ready:
            raise SolutionError("dependency cycle")
        pick = min(ready, key=lambda s: rank[s.ref])
        done.add(pick.ref)
        result.append(pick)
    return result


def ancestors(steps: list[Step]) -> dict[str, set[str]]:
    by_ref = {s.ref: s for s in steps}
    cache: dict[str, set[str]] = {}

    def walk(ref: str) -> set[str]:
        if ref not in cache:
            found: set[str] = set()
            for dep in by_ref[ref].depends_on:
                found |= {dep} | walk(dep)
            cache[ref] = found
        return cache[ref]

    return {s.ref: walk(s.ref) for s in steps}


def check_shared_files(steps: list[Step]) -> None:
    """Whole-file answers only work if tasks sharing a file are totally ordered by depends_on."""
    above = ancestors(steps)
    writers: dict[str, list[Step]] = {}
    for step in steps:
        for path in step.files:
            writers.setdefault(path, []).append(step)
    problems: list[str] = []
    for path, group in sorted(writers.items()):
        for i, a in enumerate(group):
            for b in group[i + 1 :]:
                if a.ref in above[b.ref] or b.ref in above[a.ref]:
                    continue
                if path in SHARED_BY_DEMOS and a.kind == b.kind == "demo":
                    continue
                problems.append(f"{path}: {a.ref} and {b.ref} are not ordered by depends_on")
    if problems:
        raise SolutionError(
            "tasks share a file but can run in parallel:\n  " + "\n  ".join(problems)
        )


def read_tasks(steps: list[Step]) -> dict[str, dict[str, str]]:
    """The exact content of every file of every task, checked against the plan's file lists."""
    contents: dict[str, dict[str, str]] = {}
    for step in steps:
        root = TASKS_DIR / step.ref
        found = {
            p.relative_to(root).as_posix(): p.read_text("utf-8")
            for p in sorted(root.rglob("*"))
            if p.is_file()
        }
        if set(found) != set(step.files):
            missing = sorted(set(step.files) - set(found))
            extra = sorted(set(found) - set(step.files))
            raise SolutionError(
                f"{step.ref}: files differ from the plan (missing {missing}, extra {extra})"
            )
        for path, text in found.items():
            if not text.endswith("\n") or "\r" in text:
                raise SolutionError(f"{step.ref}/{path}: must end with a newline and use LF")
        contents[step.ref] = found
    return contents


# --- Aider "whole" edit format -------------------------------------------------------------


def _wrap(name: str) -> tuple[str, str]:
    return f"<{name}>", f"</{name}>"


# aider/coders/base_coder.py: all_fences
ALL_FENCES = [
    ("`" * 3, "`" * 3),
    ("`" * 4, "`" * 4),
    _wrap("source"),
    _wrap("code"),
    _wrap("pre"),
    _wrap("codeblock"),
    _wrap("sourcecode"),
]


def choose_fence(chat_texts: Iterable[str]) -> tuple[str, str]:
    """The fence Aider uses for a chat holding these files (Coder.choose_fence)."""
    lines = "\n".join(text + "\n" for text in chat_texts).splitlines()
    for opening, closing in ALL_FENCES:
        if not any(line.startswith(opening) or line.startswith(closing) for line in lines):
            return opening, closing
    raise SolutionError("no usable fence: every fence appears in the files of the chat")


def render_reply(intro: str, files: dict[str, str], fence: tuple[str, str]) -> str:
    parts = [intro, ""]
    for path, content in files.items():
        for line in content.splitlines():
            if line.startswith(fence[0]) or line.startswith(fence[1]):
                raise SolutionError(f"{path}: a line starts with the fence {fence[0]!r}")
        if not content.endswith("\n"):
            raise SolutionError(f"{path}: content must end with a newline")
        parts.append(f"{path}\n{fence[0]}\n{content}{fence[1]}\n")
    return "\n".join(parts)


def parse_reply(reply: str, fence: tuple[str, str], chat_files: list[str]) -> dict[str, str]:
    """A port of WholeFileCoder.get_edits (aider 0.86) for the file blocks."""
    lines = reply.splitlines(keepends=True)
    edits: list[tuple[str, str, list[str]]] = []
    saw_fname: str | None = None
    fname: str | None = None
    source: str | None = None
    new_lines: list[str] = []
    for i, line in enumerate(lines):
        if line.startswith(fence[0]) or line.startswith(fence[1]):
            if fname is not None:
                saw_fname = None
                edits.append((fname, source or "", new_lines))
                fname = None
                source = None
                new_lines = []
                continue
            if i > 0:
                source = "block"
                fname = lines[i - 1].strip().strip("*").rstrip(":").strip("`").lstrip("#").strip()
                if len(fname) > 250:
                    fname = ""
                if fname and fname not in chat_files and Path(fname).name in chat_files:
                    fname = Path(fname).name
            if not fname:
                if saw_fname:
                    fname, source = saw_fname, "saw"
                elif len(chat_files) == 1:
                    fname, source = chat_files[0], "chat"
                else:
                    raise SolutionError("no filename before a fence")
        elif fname is not None:
            new_lines.append(line)
        else:
            for word in line.strip().split():
                stripped = word.rstrip(".:,;!")
                for chat_file in chat_files:
                    if stripped == f"`{chat_file}`":
                        saw_fname = chat_file
    if fname:
        edits.append((fname, source or "", new_lines))
    result: dict[str, str] = {}
    for wanted in ("block", "saw", "chat"):
        for name, origin, text in edits:
            if origin == wanted and name not in result:
                result[name] = "".join(text)
    return result


# --- simulation of the chain -----------------------------------------------------------------


class Tree:
    """The repository: the template plus what the tasks wrote so far."""

    def __init__(self) -> None:
        self.overlay: dict[str, str] = {}

    def read(self, path: str) -> str | None:
        if path in self.overlay:
            return self.overlay[path]
        base = TEMPLATE / path
        if base.is_file():
            try:
                return base.read_text("utf-8")
            except UnicodeDecodeError:
                return None
        return None

    def write(self, files: dict[str, str]) -> None:
        self.overlay.update(files)


@dataclass(frozen=True)
class Answer:
    ref: str
    role: str
    attempt: int
    reply: str
    files: dict[str, str]


def make_answer(
    tree: Tree, ref: str, role: str, attempt: int, files: dict[str, str], chat: tuple[str, ...]
) -> Answer:
    """The Aider answer writing `files`, for a chat holding `chat` (files as in `tree`)."""
    if not files:
        raise SolutionError(f"{ref} {role}: nothing to write")
    for path, content in files.items():
        if tree.read(path) == content:
            raise SolutionError(
                f"{ref} {role}: {path} is unchanged, the run would end with no commit"
            )
    fence = choose_fence(tree.read(p) or "" for p in chat)
    intro = (
        f"I will write the tests of {ref} first, one per acceptance criterion."
        if role == TEST_WRITER
        else f"Here is the implementation of {ref} (attempt {attempt})."
    )
    reply = render_reply(intro, files, fence)
    parsed = parse_reply(reply, fence, list(chat))
    if parsed != files:
        raise SolutionError(f"{ref} {role}: Aider would not parse the answer back to the files")
    return Answer(ref, role, attempt, reply, files)


def simulate(
    steps: list[Step], contents: dict[str, dict[str, str]]
) -> tuple[list[Answer], Tree, Tree]:
    """Replay the chain in dependency order.

    Returns the answers, the tree after every plan and demo task, and the same tree plus the
    comment task.
    """
    tree = Tree()
    answers: list[Answer] = []
    final: Tree | None = None
    for step in ordered(steps):
        if step.kind == "comment" and final is None:
            final = Tree()
            final.overlay = dict(tree.overlay)
        files = contents[step.ref]
        tests = {p: files[p] for p in step.files if is_test_file(p)}
        rest = {p: files[p] for p in step.files if not is_test_file(p)}
        if step.writer:
            if not tests:
                raise SolutionError(f"{step.ref}: no test file")
            answers.append(make_answer(tree, step.ref, TEST_WRITER, 1, tests, step.files))
            tree.write(tests)
        if rest:
            answers.append(make_answer(tree, step.ref, WORKER, 1, rest, step.files))
            tree.write(rest)
    assert final is not None
    return answers, final, tree


def loop_answers() -> list[Answer]:
    tree = Tree()
    chat = (LOOP_CODE_PATH, LOOP_TEST_PATH)
    answers = [
        make_answer(tree, LOOP_REF, TEST_WRITER, 1, {LOOP_TEST_PATH: LOOP_TEST}, chat),
    ]
    tree.write({LOOP_TEST_PATH: LOOP_TEST})
    for attempt in range(1, LOOP_WORKER_ATTEMPTS + 1):
        answers.append(
            make_answer(tree, LOOP_REF, WORKER, attempt, {LOOP_CODE_PATH: LOOP_CODE}, chat)
        )
    return answers


def cassette_name(answer: Answer) -> str:
    return f"{PREFIX}{answer.ref}-{answer.role}-{answer.attempt}.json"


def cassette_text(answer: Answer) -> str:
    data = {
        "version": 1,
        "match": {"marker": f"[cobble-task:{answer.ref}:{answer.role}:{answer.attempt}]"},
        "response": {"content": answer.reply, "finish_reason": "stop"},
    }
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def build() -> tuple[dict[str, str], dict[str, str]]:
    """(cassette file name -> text, tree path -> text) for the current solution."""
    steps = load_steps()
    check_shared_files(steps)
    contents = read_tasks(steps)
    answers, final, _ = simulate(steps, contents)
    answers += loop_answers()
    cassettes = {cassette_name(a): cassette_text(a) for a in answers}
    return cassettes, dict(final.overlay)


def table() -> str:
    steps = load_steps()
    rows = ["| Task | Milestone | Depends on | Files (tests first) |", "|---|---|---|---|"]
    for step in steps:
        files = sorted(step.files, key=lambda p: (not is_test_file(p), p))
        rows.append(
            f"| {step.ref} | {step.milestone} | {', '.join(step.depends_on) or '-'} "
            f"| {', '.join(files)} |"
        )
    return "\n".join(rows)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="exit 1 when out of date")
    parser.add_argument("--table", action="store_true", help="print the plan table")
    args = parser.parse_args(argv)
    if args.table:
        print(table())
        return 0
    try:
        cassettes, tree = build()
    except SolutionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    existing_tree = (
        {p.relative_to(TREE_DIR).as_posix() for p in TREE_DIR.rglob("*") if p.is_file()}
        if TREE_DIR.is_dir()
        else set()
    )
    existing_cassettes = {p.name for p in CASSETTES.glob(f"{PREFIX}*.json")}
    if args.check:
        stale = [
            f"cassettes/{name}"
            for name, text in cassettes.items()
            if not (CASSETTES / name).is_file() or (CASSETTES / name).read_text("utf-8") != text
        ]
        stale += [
            f"cassettes/{name} (stale)" for name in sorted(existing_cassettes - set(cassettes))
        ]
        stale += [
            f"tree/{path}"
            for path, text in tree.items()
            if not (TREE_DIR / path).is_file() or (TREE_DIR / path).read_text("utf-8") != text
        ]
        stale += [f"tree/{path} (stale)" for path in sorted(existing_tree - set(tree))]
        for item in stale:
            print(f"out of date: {item}", file=sys.stderr)
        return 1 if stale else 0
    for name in existing_cassettes - set(cassettes):
        (CASSETTES / name).unlink()
    for name, text in cassettes.items():
        (CASSETTES / name).write_text(text, encoding="utf-8")
    for path in existing_tree - set(tree):
        (TREE_DIR / path).unlink()
    for path, text in tree.items():
        target = TREE_DIR / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    print(f"wrote {len(cassettes)} cassettes to {CASSETTES} and {len(tree)} files to {TREE_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
