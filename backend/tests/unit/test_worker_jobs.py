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
    consume_jobs_once,
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


def test_a_crashing_handler_is_acknowledged_not_retried_forever() -> None:
    redis = FakeStreamRedis()
    ensure_jobs_group(redis)  # type: ignore[arg-type]
    enqueue_job(redis, "spec", uuid.uuid4())  # type: ignore[arg-type]
    assert consume_jobs_once(redis, "w1", handler_for(Recorder(fail=True))) == 1  # type: ignore[arg-type]
    assert redis.acked == ["1-0"]
    assert recover_pending(redis, "w2", handler_for(Recorder())) == 0  # type: ignore[arg-type]


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
    redis.xreadgroup(JOBS_GROUP, "dead-worker", {JOBS_STREAM: ">"}, count=1)
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
