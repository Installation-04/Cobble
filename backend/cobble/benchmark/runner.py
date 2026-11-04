"""Runs the benchmark for one model: ask each task, run the code in the sandbox, score it.

`quality` is the average, over the tasks, of the share of hidden cases that passed (a task whose
code could not be extracted, loaded or run counts zero). `tokens_per_second` is the completion
tokens over the time the model took to answer: the speed of this model on this machine.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from cobble.capabilities.llm import ChatResult

from .harness import Verdict, build_program, extract_code, read_verdict, task_messages
from .tasks import TASKS, VERSION, Task

log = logging.getLogger(__name__)

SANDBOX_TIMEOUT_S = 10.0

Chat = Callable[[list[dict[str, str]]], ChatResult]
RunCode = Callable[[str, float], dict[str, Any]]


@dataclass(frozen=True)
class TaskOutcome:
    task: str
    passed: int
    total: int
    # no_code | load: <Error> | missing function f | timeout | sandbox_error | no verdict | None
    error: str | None
    seconds: float
    completion_tokens: int

    @property
    def share(self) -> float:
        return self.passed / self.total if self.total else 0.0


@dataclass(frozen=True)
class BenchmarkResult:
    model: str
    version: int
    outcomes: tuple[TaskOutcome, ...] = field(default_factory=tuple)

    @property
    def quality(self) -> float:
        return sum(o.share for o in self.outcomes) / len(self.outcomes) if self.outcomes else 0.0

    @property
    def seconds(self) -> float:
        return sum(o.seconds for o in self.outcomes)

    @property
    def tokens_per_second(self) -> float | None:
        tokens = sum(o.completion_tokens for o in self.outcomes)
        return tokens / self.seconds if tokens and self.seconds > 0 else None


def run_task(
    task: Task,
    chat: Chat,
    run_code: RunCode,
    clock: Callable[[], float] = time.monotonic,
) -> TaskOutcome:
    total = len(task.cases)
    started = clock()
    reply = chat(task_messages(task))
    seconds = clock() - started
    tokens = reply.completion_tokens

    def outcome(verdict: Verdict) -> TaskOutcome:
        return TaskOutcome(task.id, verdict.passed, total, verdict.error, seconds, tokens)

    code = extract_code(reply.content)
    if code is None:
        return outcome(Verdict(0, total, "no_code"))
    program, token = build_program(task, code)
    try:
        result = run_code(program, SANDBOX_TIMEOUT_S)
    except Exception as exc:  # the sandbox itself failed: not the model's fault, say so
        log.warning("benchmark sandbox failed for %s: %s", task.id, type(exc).__name__)
        return outcome(Verdict(0, total, "sandbox_error"))
    if result.get("timed_out"):
        return outcome(Verdict(0, total, "timeout"))
    return outcome(read_verdict(str(result.get("stdout", "")), token, total))


def run_benchmark(
    model: str,
    chat: Chat,
    run_code: RunCode,
    tasks: Sequence[Task] = TASKS,
    clock: Callable[[], float] = time.monotonic,
) -> BenchmarkResult:
    outcomes = tuple(run_task(task, chat, run_code, clock) for task in tasks)
    return BenchmarkResult(model, VERSION, outcomes)
