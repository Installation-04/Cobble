from __future__ import annotations

import re

from cobble.scheduler import prompts
from cobble.scheduler.prompts import PromptTask

TASK = PromptTask(
    ref="T-012",
    title="Create invoices",
    milestone="M2",
    files=("app/api/invoices.py", "tests/api/test_invoices.py"),
    acceptance=("POST returns 201", "Negative amount returns 422"),
    tests="tests/api/test_invoices.py",
    role="backend",
    size="S",
)
MARKER = re.compile(r"^\[cobble-task:(T-\d+):(test-writer|worker):(\d+)\]$")


def test_marker_format() -> None:
    assert prompts.marker("T-001", "worker", 2) == "[cobble-task:T-001:worker:2]"
    assert MARKER.match(prompts.marker("T-001", "test-writer", 1))


def test_writer_prompt_starts_with_its_marker_and_asks_for_tests_first() -> None:
    text = prompts.writer_instructions(TASK)
    first = text.splitlines()[0]
    assert first == "[cobble-task:T-012:test-writer:1]"
    assert "FIRST" in text
    assert "Do not implement the feature" in text
    for needle in ("Create invoices", "POST returns 201", "Negative amount returns 422"):
        assert needle in text
    assert "tests/api/test_invoices.py" in text
    assert "uv run pytest -q tests/api/test_invoices.py" in text
    assert "PROJECT.md" in text


def test_worker_prompt_makes_the_tests_pass() -> None:
    text = prompts.worker_instructions(TASK, 1)
    assert text.splitlines()[0] == "[cobble-task:T-012:worker:1]"
    assert "make the tests pass" in text.lower() or "until they pass" in text
    assert "app/api/invoices.py" in text
    assert "previous attempt" not in text


def test_retry_prompt_carries_the_failure_tail() -> None:
    log = "x" * 10_000 + "\nAssertionError: expected 422"
    text = prompts.worker_instructions(TASK, 3, log)
    assert text.splitlines()[0] == "[cobble-task:T-012:worker:3]"
    assert "AssertionError: expected 422" in text
    assert "The previous attempt failed" in text
    assert len(text) < 8000  # the log is cut to its end


def test_prompts_are_deterministic() -> None:
    assert prompts.writer_instructions(TASK) == prompts.writer_instructions(TASK)
    assert prompts.worker_instructions(TASK, 2, "boom") == prompts.worker_instructions(
        TASK, 2, "boom"
    )
    assert prompts.worker_instructions(TASK, 2, "boom") != prompts.worker_instructions(
        TASK, 3, "boom"
    )


def test_test_command_depends_on_the_test_file() -> None:
    assert prompts.local_test_command("tests/test_x.py") == "uv run pytest -q tests/test_x.py"
    web = prompts.local_test_command("tests/web/x.test.js")
    # A fresh checkout has no node_modules: dependencies are installed before the tests run.
    assert web.index("install --frozen-lockfile") < web.index("test")
