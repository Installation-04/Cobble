"""The scheduler follows the installed modules: swap between ticks, keep on doubt."""

from __future__ import annotations

import threading
import uuid
from typing import Any, cast

import pytest

from cobble.scheduler.engine import Scheduler
from cobble.scheduler.supervisor import BuildResult, SchedulerSupervisor, SchedulerUnavailable


class Stub:
    def __init__(self, name: str, log: list[str]) -> None:
        self.name = name
        self.log = log

    def reconcile(self) -> None:
        self.log.append(f"{self.name}:reconcile")

    def tick(self) -> None:
        self.log.append(f"{self.name}:tick")

    def run_start_job(self, project_id: uuid.UUID) -> bool:
        self.log.append(f"{self.name}:start")
        return True

    def run_revert_job(self, project_id: uuid.UUID, ref: str) -> bool:
        self.log.append(f"{self.name}:revert:{ref}")
        return True


def sched(stub: Stub) -> Scheduler:
    return cast(Scheduler, stub)


class Rig:
    def __init__(self) -> None:
        self.log: list[str] = []
        self.generation: Any = 1
        self.builds: list[BuildResult] = []
        self.calls = 0
        self.supervisor = SchedulerSupervisor(self._build, self._generation, 0.0)

    def _build(self) -> BuildResult:
        self.calls += 1
        item = self.builds.pop(0)
        return item

    def _generation(self) -> int:
        if isinstance(self.generation, Exception):
            raise self.generation
        return int(self.generation)


def test_the_first_refresh_builds_and_reconciles_once() -> None:
    rig = Rig()
    rig.builds = [BuildResult(sched(Stub("a", rig.log)))]
    assert rig.supervisor.refresh() is True
    assert rig.log == ["a:reconcile"]
    assert rig.supervisor.refresh() is False  # same generation: nothing rebuilt
    assert rig.calls == 1


def test_a_new_generation_swaps_the_scheduler() -> None:
    rig = Rig()
    rig.builds = [BuildResult(sched(Stub("a", rig.log))), BuildResult(sched(Stub("b", rig.log)))]
    rig.supervisor.refresh()
    rig.generation = 2
    assert rig.supervisor.refresh() is True
    rig.supervisor.run_start_job(uuid.uuid4())
    assert rig.log == ["a:reconcile", "b:reconcile", "b:start"]


def test_a_swap_never_happens_in_the_middle_of_a_tick() -> None:
    rig = Rig()
    stop = threading.Event()
    seen: list[str] = []

    class Slow(Stub):
        def tick(self) -> None:
            rig.generation = 2  # the modules change while this tick runs
            seen.append(f"{self.name}:tick-start")
            assert rig.supervisor.current is not None and rig.supervisor.current.name == self.name  # type: ignore[attr-defined]
            seen.append(f"{self.name}:tick-end")
            stop.set()

    rig.builds = [BuildResult(sched(Slow("a", rig.log))), BuildResult(sched(Stub("b", rig.log)))]
    rig.supervisor.run_forever(stop)
    assert seen == ["a:tick-start", "a:tick-end"]  # the tick finished on the old providers
    rig.supervisor.refresh()
    assert rig.supervisor.current is not None
    assert rig.supervisor.current.name == "b"  # type: ignore[attr-defined]


def test_without_a_scheduler_jobs_are_refused_with_a_clear_error() -> None:
    rig = Rig()
    rig.builds = [BuildResult(None)]
    rig.supervisor.refresh()
    with pytest.raises(SchedulerUnavailable):
        rig.supervisor.run_start_job(uuid.uuid4())
    with pytest.raises(SchedulerUnavailable):
        rig.supervisor.run_revert_job(uuid.uuid4(), "m1")


def test_uninstalling_the_last_module_turns_the_scheduler_off() -> None:
    rig = Rig()
    rig.builds = [BuildResult(sched(Stub("a", rig.log))), BuildResult(None)]
    rig.supervisor.refresh()
    rig.generation = 2
    rig.supervisor.refresh()
    assert rig.supervisor.current is None


def test_an_unreadable_generation_keeps_the_scheduler() -> None:
    rig = Rig()
    rig.builds = [BuildResult(sched(Stub("a", rig.log)))]
    rig.supervisor.refresh()
    rig.generation = RuntimeError("db down")
    assert rig.supervisor.refresh() is False
    assert rig.supervisor.current is not None


def test_a_failing_build_keeps_the_scheduler_and_is_retried() -> None:
    rig = Rig()
    stub = Stub("a", rig.log)
    rig.builds = [BuildResult(sched(stub))]
    rig.supervisor.refresh()
    rig.generation = 2

    def boom() -> BuildResult:
        raise RuntimeError("boom")

    rig.supervisor._build = boom
    assert rig.supervisor.refresh() is False
    assert rig.supervisor.current is stub
    rig.supervisor._build = rig._build
    rig.builds = [BuildResult(sched(Stub("b", rig.log)))]
    assert rig.supervisor.refresh() is True  # not marked as seen: retried


def test_a_keep_answer_leaves_everything_and_a_non_final_one_is_retried() -> None:
    rig = Rig()
    first = Stub("a", rig.log)
    rig.builds = [BuildResult(sched(first), final=False)]
    rig.supervisor.refresh()
    rig.builds = [BuildResult(None, final=False, keep=True)]
    assert rig.supervisor.refresh() is False  # same generation but not settled: asked again
    assert rig.supervisor.current is first
    rig.builds = [BuildResult(sched(Stub("b", rig.log)))]
    assert rig.supervisor.refresh() is True
    assert rig.supervisor.refresh() is False  # now settled
    assert rig.calls == 3


def test_a_tick_that_raises_does_not_stop_the_loop() -> None:
    rig = Rig()
    stop = threading.Event()
    count = 0

    class Flaky(Stub):
        def tick(self) -> None:
            nonlocal count
            count += 1
            if count == 1:
                raise RuntimeError("tick failed")
            stop.set()

    rig.builds = [BuildResult(sched(Flaky("a", rig.log)))]
    rig.supervisor.run_forever(stop)
    assert count == 2
