"""Deterministic instructions for the coding agents.

Same task, same attempt, same failure text: same prompt. The first line is always the marker
`[cobble-task:<ref>:<role>:<attempt>]`, which lets the fake provider replay a recorded answer
whatever the rest of the prompt says (see providers/fake-llm).
"""

from __future__ import annotations

from dataclasses import dataclass

TEST_WRITER = "test-writer"
WORKER = "worker"
FAILURE_TAIL_CHARS = 4000
NO_TESTS = "n/a"  # `tests` of a demo task: the test-writer step is skipped
ANY_FILE = "*"

CONVENTIONS = (
    "Repository conventions:\n"
    "- Read PROJECT.md first: stack, conventions and decisions.\n"
    "- Work only on the files listed below; do not touch other files unless a test needs it.\n"
    "- Keep the change small and focused. No secrets in the code.\n"
    "- Commit to the current branch; do not switch branches and do not push to main.\n"
)


@dataclass(frozen=True)
class PromptTask:
    ref: str
    title: str
    milestone: str
    files: tuple[str, ...]
    acceptance: tuple[str, ...]
    tests: str
    role: str
    size: str


def marker(ref: str, role: str, attempt: int) -> str:
    return f"[cobble-task:{ref}:{role}:{attempt}]"


def tail(text: str, limit: int = FAILURE_TAIL_CHARS) -> str:
    """The last `limit` characters (a failure log's useful part is its end)."""
    text = text.strip()
    return text if len(text) <= limit else "..." + text[-limit:]


def local_test_command(tests: str) -> str:
    """How the agent runs the task's tests locally."""
    if tests.endswith(".py"):
        return f"uv run pytest -q {tests}"
    if tests == NO_TESTS:
        return "uv run pytest -q"  # a demo task adds no test file: the whole suite must stay green
    # A fresh checkout has no node_modules: install from the lockfile (the runner image ships a
    # pre-warmed store, so this is offline-friendly) before running the tests.
    return (
        "pnpm --dir frontend install --frozen-lockfile --prefer-offline && pnpm --dir frontend test"
    )


def _body(task: PromptTask) -> str:
    criteria = "\n".join(f"- {item}" for item in task.acceptance)
    files = "\n".join(
        "- any file the change needs" if path == ANY_FILE else f"- {path}" for path in task.files
    )
    return (
        f"Task {task.ref}: {task.title}\n"
        f"Milestone: {task.milestone}. Size: {task.size}. Area: {task.role}.\n\n"
        f"Acceptance criteria:\n{criteria}\n\n"
        f"Files:\n{files}\n\n"
        f"Test file: {task.tests}\n"
        f"Test command: {local_test_command(task.tests)}\n\n"
        f"{CONVENTIONS}"
    )


def writer_instructions(task: PromptTask) -> str:
    """First step of every task: tests only, written from the acceptance criteria."""
    return (
        f"{marker(task.ref, TEST_WRITER, 1)}\n"
        "You are the test writer. Write the tests FIRST, before any implementation exists.\n"
        f"Write only the test file {task.tests} (plus fixtures it needs): one test per "
        "acceptance criterion, each failing for the right reason until the feature exists. "
        "Do not implement the feature.\n\n"
        f"{_body(task)}"
    )


def worker_instructions(task: PromptTask, attempt: int, failure: str | None = None) -> str:
    """Second step: make the tests pass. `failure` is the previous attempt's CI log or error."""
    text = (
        f"{marker(task.ref, WORKER, attempt)}\n"
        f"You are the implementer (attempt {attempt}). The tests in {task.tests} are already "
        "written: do not weaken or delete them. Implement the feature until they pass locally "
        "with the test command, then stop.\n\n"
        f"{_body(task)}"
    )
    if failure:
        text += (
            "\nThe previous attempt failed. End of its log:\n"
            f"```\n{tail(failure)}\n```\n"
            "Fix the cause of this failure.\n"
        )
    return text


def demo_instructions(task: PromptTask, attempt: int, failure: str | None = None) -> str:
    """Demo data task: no test-writer step, the agent only edits `app/seed.py`."""
    text = (
        f"{marker(task.ref, WORKER, attempt)}\n"
        f"You prepare the demo of milestone {task.milestone} (attempt {attempt}). "
        "Edit app/seed.py so that `seed()` fills an EMPTY database with realistic, varied "
        "sample data that shows what the application does at this milestone: plausible names, "
        "dates and quantities, a mix of states, enough rows to fill a screen. Never lorem "
        "ipsum. `seed()` runs once when the demo container starts and must be idempotent: "
        "insert only when the tables are empty. No network access, no secrets, no real "
        "personal data. Do not change other files and do not weaken any test; the existing "
        "test suite must keep passing (there is no new test file for this task).\n\n"
        f"{_body(task)}"
    )
    if failure:
        text += (
            "\nThe previous attempt failed. End of its log:\n"
            f"```\n{tail(failure)}\n```\n"
            "Fix the cause of this failure.\n"
        )
    return text
