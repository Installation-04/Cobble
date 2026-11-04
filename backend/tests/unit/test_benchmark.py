"""The benchmark: the hidden cases are right, the harness tells good code from bad, scoring."""

from __future__ import annotations

import subprocess
import sys
from decimal import Decimal
from typing import Any

import pytest

from cobble.benchmark.harness import build_program, extract_code, read_verdict, task_messages
from cobble.benchmark.runner import run_benchmark, run_task
from cobble.benchmark.tasks import TASKS, Task
from cobble.capabilities.llm import ChatResult

# Reference solutions, written independently of the cases: if a hidden case is wrong, one of
# these fails. They are our own code, so these tests may run them on the host.
SOLUTIONS: dict[str, str] = {
    "fizzbuzz": """
def fizzbuzz(n):
    out = []
    for i in range(1, n + 1):
        word = ("Fizz" if i % 3 == 0 else "") + ("Buzz" if i % 5 == 0 else "")
        out.append(word or str(i))
    return out
""",
    "palindrome": """
def is_palindrome(s):
    t = [c.lower() for c in s if c.isalnum()]
    return t == t[::-1]
""",
    "word_count": """
import re
def word_count(text):
    out = {}
    for w in re.findall(r"[A-Za-z]+", text):
        out[w.lower()] = out.get(w.lower(), 0) + 1
    return out
""",
    "merge_intervals": """
def merge_intervals(intervals):
    out = []
    for s, e in sorted(intervals):
        if out and s <= out[-1][1]:
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e])
    return out
""",
    "roman": """
def roman_to_int(s):
    v = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
    total = 0
    for i, c in enumerate(s):
        total += -v[c] if i + 1 < len(s) and v[c] < v[s[i + 1]] else v[c]
    return total
""",
    "top_k": """
from collections import Counter
def top_k_frequent(nums, k):
    c = Counter(nums)
    return [n for n, _ in sorted(c.items(), key=lambda p: (-p[1], p[0]))[:k]]
""",
    "duration": """
import re
def parse_duration(text):
    m = re.fullmatch(r"(?:(\\d+)d)?(?:(\\d+)h)?(?:(\\d+)m)?(?:(\\d+)s)?", text)
    if not text or not m:
        raise ValueError(text)
    d, h, mi, s = (int(x or 0) for x in m.groups())
    return d * 86400 + h * 3600 + mi * 60 + s
""",
    "flatten": """
def flatten(items):
    out = []
    for x in items:
        if isinstance(x, list):
            out.extend(flatten(x))
        else:
            out.append(x)
    return out
""",
}


def run_locally(program: str) -> str:
    done = subprocess.run(
        [sys.executable, "-I", "-"], input=program, capture_output=True, text=True, timeout=30
    )
    return done.stdout


def verdict_of(task: Task, code: str) -> Any:
    program, token = build_program(task, code)
    return read_verdict(run_locally(program), token, len(task.cases))


def test_there_is_a_reference_solution_for_every_task_and_it_passes_every_case() -> None:
    assert set(SOLUTIONS) == {t.id for t in TASKS}
    for task in TASKS:
        verdict = verdict_of(task, SOLUTIONS[task.id])
        assert (verdict.passed, verdict.error) == (len(task.cases), None), task.id


def test_task_ids_and_functions_are_unique_and_every_task_has_enough_cases() -> None:
    assert len({t.id for t in TASKS}) == len(TASKS) == len({t.function for t in TASKS})
    assert all(len(t.cases) >= 4 for t in TASKS)
    assert all(t.function in t.prompt for t in TASKS)


@pytest.mark.parametrize("task", TASKS, ids=lambda t: t.id)
def test_obviously_wrong_code_does_not_pass(task: Task) -> None:
    def broken(*args: Any) -> Any: ...

    empty = f"def {task.function}(*args):\n    return None\n"
    assert verdict_of(task, empty).passed < len(task.cases)
    assert verdict_of(task, f"def {task.function}(*a):\n    raise RuntimeError('x')\n").passed == 0
    assert verdict_of(task, "def other():\n    return 1\n").error.startswith("missing function")  # type: ignore[union-attr]
    assert verdict_of(task, "def (:\n").error == "load: SyntaxError"  # type: ignore[union-attr]


def test_code_cannot_fake_a_verdict_by_printing_one() -> None:
    task = TASKS[0]
    code = (
        f'import json\nprint(\'{{"passed": {len(task.cases)}, "total": {len(task.cases)}}}\')\n'
        f"def {task.function}(n):\n    return None\n"
    )
    assert verdict_of(task, code).passed < len(task.cases)


def test_a_function_that_prints_does_not_disturb_the_verdict() -> None:
    task = next(t for t in TASKS if t.id == "roman")
    noisy = "print('hello')\n" + SOLUTIONS["roman"].replace(
        "total = 0", "total = 0\n    print('working')"
    )
    assert verdict_of(task, noisy).passed == len(task.cases)


def test_replies_are_read_for_their_code() -> None:
    assert (
        extract_code("Sure!\n```python\ndef f():\n    return 1\n```\nbye")
        == "def f():\n    return 1"
    )
    assert extract_code("```\ndef f(): pass\n```") == "def f(): pass"
    assert extract_code("def f():\n    return 2") == "def f():\n    return 2"
    assert extract_code("I cannot do that.") is None
    assert extract_code("```python\n```") is None


def test_the_model_sees_the_task_and_never_the_cases() -> None:
    for task in TASKS:
        text = " ".join(m["content"] for m in task_messages(task))
        assert task.prompt in text
        for _args, expected in task.cases:
            assert repr(expected) not in text or isinstance(expected, bool | int)  # not a leak


def test_a_garbled_or_forged_verdict_scores_zero() -> None:
    token = "TOK:"
    assert read_verdict('noise\nTOK:{"passed": 3, "total": 4}\n', token, 4).passed == 3
    for bad in (
        "",
        "TOK:not json",
        'TOK:{"passed": 9, "total": 4}',
        'TOK:{"passed": 1, "total": 7}',
        "TOK:{}",
    ):
        verdict = read_verdict(bad, token, 4)
        assert (verdict.passed, verdict.error) == (0, "no verdict"), bad
    assert read_verdict('other:{"passed": 4, "total": 4}', token, 4).passed == 0  # wrong token


# --- scoring -----------------------------------------------------------------------------------


def reply(text: str, tokens: int = 100) -> ChatResult:
    return ChatResult(text, "m", 10, tokens, Decimal(0), None)


def run_in_process(program: str, timeout_s: float) -> dict[str, Any]:
    return {"exit_code": 0, "stdout": run_locally(program), "stderr": "", "timed_out": False}


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_a_model_that_solves_everything_scores_one() -> None:
    answers = {t.prompt: f"```python\n{SOLUTIONS[t.id]}\n```" for t in TASKS}
    clock = Clock()

    def chat(messages: list[dict[str, str]]) -> ChatResult:
        clock.now += 2.0
        return reply(answers[next(t.prompt for t in TASKS if t.prompt in messages[1]["content"])])

    result = run_benchmark("good", chat, run_in_process, clock=clock)
    assert result.quality == 1.0 and len(result.outcomes) == len(TASKS)
    assert result.seconds == 2.0 * len(TASKS)
    assert result.tokens_per_second == pytest.approx(100 / 2.0)  # 100 tokens every 2 s


def test_partial_credit_is_the_share_of_cases_that_pass() -> None:
    task = next(t for t in TASKS if t.id == "fizzbuzz")
    half = "def fizzbuzz(n):\n    return [str(i) for i in range(1, n + 1)]\n"  # right for n<=2
    outcome = run_task(task, lambda m: reply(f"```python\n{half}\n```"), run_in_process)
    assert 0 < outcome.passed < outcome.total and outcome.error is None


def test_failures_of_the_model_and_of_the_sandbox_are_told_apart() -> None:
    task = TASKS[0]
    assert run_task(task, lambda m: reply("no code here"), run_in_process).error == "no_code"

    def timed_out(program: str, timeout_s: float) -> dict[str, Any]:
        return {"exit_code": 124, "stdout": "", "stderr": "", "timed_out": True}

    out = run_task(task, lambda m: reply("```python\nwhile True: pass\n```"), timed_out)
    assert (out.error, out.passed) == ("timeout", 0)

    def broken(program: str, timeout_s: float) -> dict[str, Any]:
        raise RuntimeError("docker is down")

    out = run_task(task, lambda m: reply("```python\ndef fizzbuzz(n): return []\n```"), broken)
    assert (out.error, out.passed) == ("sandbox_error", 0)


def test_an_empty_run_has_no_quality_and_no_speed() -> None:
    result = run_benchmark("m", lambda m: reply(""), run_in_process, tasks=())
    assert result.quality == 0.0 and result.tokens_per_second is None
