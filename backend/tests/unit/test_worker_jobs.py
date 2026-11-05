from __future__ import annotations

import threading
import time
import uuid
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from cobble.config import Settings
from cobble.db import Message
from cobble.events import JOBS_GROUP, JOBS_STREAM, enqueue_job
from cobble.orchestrator.service import PlannerService
from cobble.worker import (
    DEAD_STREAM,
    MAX_DELIVERIES,
    RECLAIM_IDLE_MS,
    RETRY_DELAY_MS,
    consume_jobs_once,
    consumer_name,
    ensure_jobs_group,
    make_job_handler,
    recover_pending,
    run_jobs,
)

from .fakes import FakeStreamRedis
from .planning import ScriptedLLM, events_of, make_project


class Recorder:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.jobs: list[tuple[str, uuid.UUID, str | None, str | None]] = []
        self.pending_during_run: list[int] = []
        self.redis: FakeStreamRedis | None = None

    def run_job(
        self,
        kind: str,
        project_id: uuid.UUID,
        *,
        feedback: str | None = None,
        message_id: str | None = None,
    ) -> bool:
        self.jobs.append((kind, project_id, feedback, message_id))
        if self.redis is not None:
            self.pending_during_run.append(len(self.redis.pending[(JOBS_STREAM, JOBS_GROUP)]))
        if self.fail:
            raise RuntimeError("boom")
        return True


def handler_for(recorder: Recorder) -> Any:
    return make_job_handler(recorder)  # type: ignore[arg-type]


def test_jobs_group_starts_at_the_beginning_of_the_stream() -> None:
    redis = FakeStreamRedis()
    enqueue_job(redis, "spec", uuid.uuid4())  # type: ignore[arg-type]  # queued before any worker
    ensure_jobs_group(redis)  # type: ignore[arg-type]
    ensure_jobs_group(redis)  # type: ignore[arg-type]  # idempotent (BUSYGROUP is ignored)
    recorder = Recorder()
    assert consume_jobs_once(redis, "w1", handler_for(recorder)) == 1  # type: ignore[arg-type]


def test_job_is_acknowledged_only_after_it_ran() -> None:
    redis = FakeStreamRedis()
    ensure_jobs_group(redis)  # type: ignore[arg-type]
    pid = uuid.uuid4()
    enqueue_job(redis, "plan", pid, feedback="smaller")  # type: ignore[arg-type]
    recorder = Recorder()
    recorder.redis = redis
    assert consume_jobs_once(redis, "w1", handler_for(recorder)) == 1  # type: ignore[arg-type]
    assert recorder.jobs == [("plan", pid, "smaller", None)]
    assert recorder.pending_during_run == [1]  # still pending while running
    assert redis.acked == ["1-0"]
    assert redis.pending[(JOBS_STREAM, JOBS_GROUP)] == {}
    assert consume_jobs_once(redis, "w1", handler_for(recorder)) == 0  # type: ignore[arg-type]


def test_reply_job_carries_the_message_id() -> None:
    redis = FakeStreamRedis()
    ensure_jobs_group(redis)  # type: ignore[arg-type]
    pid = uuid.uuid4()
    enqueue_job(redis, "reply", pid, message_id="m-1")  # type: ignore[arg-type]
    recorder = Recorder()
    consume_jobs_once(redis, "w1", handler_for(recorder))  # type: ignore[arg-type]
    assert recorder.jobs == [("reply", pid, None, "m-1")]


def test_a_crashing_handler_leaves_the_job_pending_and_it_is_retried_later() -> None:
    redis = FakeStreamRedis()
    ensure_jobs_group(redis)  # type: ignore[arg-type]
    pid = uuid.uuid4()
    enqueue_job(redis, "spec", pid)  # type: ignore[arg-type]
    assert consume_jobs_once(redis, "w1", handler_for(Recorder(fail=True))) == 0  # type: ignore[arg-type]
    assert redis.acked == []  # not lost: still pending
    good = Recorder()
    # Too early: the retry delay of the worker's own crashed jobs has not elapsed.
    assert recover_pending(redis, "w1", handler_for(good), RECLAIM_IDLE_MS, RETRY_DELAY_MS) == 0  # type: ignore[arg-type]
    redis.advance(RETRY_DELAY_MS)
    assert recover_pending(redis, "w1", handler_for(good), RECLAIM_IDLE_MS, RETRY_DELAY_MS) == 1  # type: ignore[arg-type]
    assert good.jobs == [("spec", pid, None, None)]
    assert redis.acked == ["1-0"]
    assert redis.entries(DEAD_STREAM) == []


def test_a_job_that_keeps_crashing_is_dead_lettered_after_a_bounded_number_of_tries() -> None:
    redis = FakeStreamRedis()
    ensure_jobs_group(redis)  # type: ignore[arg-type]
    pid = uuid.uuid4()
    enqueue_job(redis, "plan", pid, feedback="x")  # type: ignore[arg-type]
    bad = Recorder(fail=True)
    assert consume_jobs_once(redis, "w1", handler_for(bad)) == 0  # type: ignore[arg-type]  # delivery 1
    for expected in (0, 1):  # delivery 2 retries, delivery 3 gives up
        redis.advance(RETRY_DELAY_MS)
        got = recover_pending(redis, "w1", handler_for(bad), RECLAIM_IDLE_MS, RETRY_DELAY_MS)  # type: ignore[arg-type]
        assert got == expected
    assert len(bad.jobs) == MAX_DELIVERIES == 3
    assert redis.acked == ["1-0"]
    dead = redis.entries(DEAD_STREAM)
    assert len(dead) == 1
    assert dead[0]["deliveries"] == "3" and dead[0]["entry_id"] == "1-0"
    assert "RuntimeError: boom" in dead[0]["error"] and str(pid) in dead[0]["job"]
    name, payload = events_of(redis, pid)[-1]
    assert (name, payload) == ("job.failed", {"kind": "plan", "code": "crashed"})
    # Nothing is left to loop on.
    redis.advance(RECLAIM_IDLE_MS)
    assert recover_pending(redis, "w2", handler_for(bad)) == 0  # type: ignore[arg-type]
    assert len(bad.jobs) == 3


def test_a_job_that_kills_its_worker_every_time_is_dead_lettered_without_running() -> None:
    redis = FakeStreamRedis()
    ensure_jobs_group(redis)  # type: ignore[arg-type]
    pid = uuid.uuid4()
    enqueue_job(redis, "spec", pid)  # type: ignore[arg-type]
    redis.xreadgroup(JOBS_GROUP, "w1", {JOBS_STREAM: ">"}, count=1)  # delivery 1, then SIGKILL
    for _ in range(MAX_DELIVERIES - 1):  # deliveries 2 and 3, each also ends in a kill
        redis.xclaim(JOBS_STREAM, JOBS_GROUP, "w1", 0, ["1-0"])
    recorder = Recorder()
    assert recover_pending(redis, "w1", handler_for(recorder), RECLAIM_IDLE_MS, 0) == 1  # type: ignore[arg-type]
    assert recorder.jobs == []  # never run a fourth time
    assert redis.acked == ["1-0"]
    assert redis.entries(DEAD_STREAM)[0]["error"] == "worker died repeatedly"
    assert events_of(redis, pid)[-1][1]["code"] == "crashed"


def test_a_live_peers_job_is_not_stolen_but_a_dead_ones_is() -> None:
    redis = FakeStreamRedis()
    ensure_jobs_group(redis)  # type: ignore[arg-type]
    pid = uuid.uuid4()
    enqueue_job(redis, "spec", pid)  # type: ignore[arg-type]
    redis.xreadgroup(JOBS_GROUP, "peer", {JOBS_STREAM: ">"}, count=1)  # the peer is running it
    redis.advance(60_000)
    recorder = Recorder()
    # Start-up of a second worker: its own entries would be taken at once, the peer's are not.
    assert recover_pending(redis, "me", handler_for(recorder), RECLAIM_IDLE_MS, 0) == 0  # type: ignore[arg-type]
    assert recorder.jobs == [] and redis.acked == []
    redis.advance(RECLAIM_IDLE_MS)  # the peer never answered again: presumed dead
    assert recover_pending(redis, "me", handler_for(recorder), RECLAIM_IDLE_MS, 0) == 1  # type: ignore[arg-type]
    assert recorder.jobs == [("spec", pid, None, None)]


def test_consumer_name_is_stable_and_can_be_pinned(monkeypatch: pytest.MonkeyPatch) -> None:
    import socket

    monkeypatch.delenv("COBBLE_WORKER_NAME", raising=False)
    assert consumer_name() == socket.gethostname() == consumer_name()
    monkeypatch.setenv("COBBLE_WORKER_NAME", "worker-a")
    assert consumer_name() == "worker-a"


def test_malformed_jobs_are_dropped_and_acknowledged() -> None:
    redis = FakeStreamRedis()
    ensure_jobs_group(redis)  # type: ignore[arg-type]
    redis.xadd(JOBS_STREAM, {"job": "{not json"})
    redis.xadd(JOBS_STREAM, {"job": '{"kind": "spec", "project_id": "nope"}'})
    redis.xadd(JOBS_STREAM, {"other": "x"})
    recorder = Recorder()
    handler = handler_for(recorder)
    assert [consume_jobs_once(redis, "w1", handler) for _ in range(3)] == [1, 1, 1]  # type: ignore[arg-type]
    assert recorder.jobs == []
    assert redis.acked == ["1-0", "2-0", "3-0"]


def test_pending_jobs_of_a_dead_worker_are_resumed() -> None:
    redis = FakeStreamRedis()
    ensure_jobs_group(redis)  # type: ignore[arg-type]
    pid = uuid.uuid4()
    enqueue_job(redis, "spec", pid)  # type: ignore[arg-type]
    # The first worker reads the job, then dies before acknowledging it.
    redis.xreadgroup(JOBS_GROUP, "dead-worker", {JOBS_STREAM: ">"}, count=1)
    assert redis.acked == []

    recorder = Recorder()
    assert recover_pending(redis, "new-worker", handler_for(recorder), 0) == 1  # type: ignore[arg-type]
    assert recorder.jobs == [("spec", pid, None, None)]
    assert redis.acked == ["1-0"]
    assert recover_pending(redis, "new-worker", handler_for(recorder), 0) == 0  # type: ignore[arg-type]


def wait_for(condition: Any, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.01)
    return False


def test_run_jobs_resumes_pending_then_processes_new_jobs() -> None:
    redis = FakeStreamRedis()
    ensure_jobs_group(redis)  # type: ignore[arg-type]
    first, second = uuid.uuid4(), uuid.uuid4()
    enqueue_job(redis, "spec", first)  # type: ignore[arg-type]
    redis.xreadgroup(JOBS_GROUP, "w", {JOBS_STREAM: ">"}, count=1)  # this worker, before a restart
    enqueue_job(redis, "plan", second)  # type: ignore[arg-type]

    recorder = Recorder()
    stop = threading.Event()
    thread = threading.Thread(target=run_jobs, args=(redis, stop, handler_for(recorder), "w"))
    thread.start()
    try:
        assert wait_for(lambda: len(recorder.jobs) == 2)
    finally:
        stop.set()
        thread.join(timeout=5)
    assert not thread.is_alive()
    assert [job[:2] for job in recorder.jobs] == [("spec", first), ("plan", second)]
    assert sorted(redis.acked) == ["1-0", "2-0"]


def test_run_jobs_survives_a_redis_outage() -> None:
    redis = FakeStreamRedis(fail=True)
    stop = threading.Event()
    thread = threading.Thread(target=run_jobs, args=(redis, stop, handler_for(Recorder()), "w"))
    thread.start()
    time.sleep(0.05)
    assert thread.is_alive()
    stop.set()
    thread.join(timeout=5)
    assert not thread.is_alive()


def test_a_reply_job_runs_through_the_real_planner(sessions: sessionmaker[Session]) -> None:
    pid = make_project(sessions)
    with sessions() as db:
        message = Message(project_id=pid, role="user", content="I want a to-do app")
        db.add(message)
        db.commit()
        message_id = str(message.id)
    redis = FakeStreamRedis()
    planner = PlannerService(sessions, ScriptedLLM("Who will use it?"), redis, Settings())  # type: ignore[arg-type]
    ensure_jobs_group(redis)  # type: ignore[arg-type]
    enqueue_job(redis, "reply", pid, message_id=message_id)  # type: ignore[arg-type]

    assert consume_jobs_once(redis, "w1", make_job_handler(planner)) == 1  # type: ignore[arg-type]

    with sessions() as db:
        roles = [m.role for m in db.scalars(select(Message).order_by(Message.created_at))]
    assert roles == ["user", "assistant"]
    assert [name for name, _ in events_of(redis, pid)] == ["job.started", "message.created"]
    assert redis.acked == ["1-0"]


def test_a_failed_job_publishes_job_failed_and_is_acknowledged(
    sessions: sessionmaker[Session],
) -> None:
    pid = make_project(sessions)
    redis = FakeStreamRedis()
    planner = PlannerService(sessions, ScriptedLLM(RuntimeError("x")), redis, Settings())  # type: ignore[arg-type]
    ensure_jobs_group(redis)  # type: ignore[arg-type]
    with sessions() as db:
        db.add(Message(project_id=pid, role="user", content="hi"))
        db.commit()
    enqueue_job(redis, "reply", pid)  # type: ignore[arg-type]
    consume_jobs_once(redis, "w1", make_job_handler(planner))  # type: ignore[arg-type]
    assert events_of(redis, pid)[-1][0] == "job.failed"
    assert redis.acked == ["1-0"]


def test_build_planner_wires_the_cost_router() -> None:
    from cobble.router.costs import CostRouter
    from cobble.worker import build_planner

    planner = build_planner(Settings(role_models={"planner": "strong"}), FakeStreamRedis())  # type: ignore[arg-type]
    router = planner._llm
    assert isinstance(router, CostRouter)
    from cobble.capabilities.llm import Role

    assert router.model_for(Role.PLANNER) == "strong"
    assert router.model_for(Role.WORKER) == "fake"


@pytest.mark.parametrize("name", ["cobble:jobs", "workers"])
def test_stream_and_group_names_match_the_adr(name: str) -> None:
    assert name in (JOBS_STREAM, JOBS_GROUP)


class NoScheduler:
    """A supervisor whose providers are gone (the last git/CI module was uninstalled)."""

    def __init__(self) -> None:
        self.calls = 0

    def run_start_job(self, project_id: uuid.UUID) -> bool:
        self.calls += 1
        from cobble.scheduler.supervisor import SchedulerUnavailable

        raise SchedulerUnavailable

    run_revert_job = None


@pytest.mark.parametrize("kind", ["start", "revert"])
def test_a_job_for_a_scheduler_that_is_off_fails_visibly_and_is_acknowledged(
    sessions: sessionmaker[Session], kind: str
) -> None:
    pid = make_project(sessions)
    redis = FakeStreamRedis()
    supervisor = NoScheduler()
    if kind == "revert":
        from cobble.scheduler.supervisor import SchedulerUnavailable

        def revert(_pid: uuid.UUID, _ref: str) -> bool:
            raise SchedulerUnavailable

        supervisor.run_revert_job = revert  # type: ignore[assignment]
    ensure_jobs_group(redis)  # type: ignore[arg-type]
    enqueue_job(redis, kind, pid)  # type: ignore[arg-type]
    handler = make_job_handler(Recorder(), supervisor, redis)  # type: ignore[arg-type]
    consume_jobs_once(redis, "w1", handler)  # type: ignore[arg-type]
    name, payload = events_of(redis, pid)[-1]
    assert name == "job.failed"
    assert payload["code"] == "scheduler_unavailable" and payload["kind"] == kind
    assert redis.acked == ["1-0"]
