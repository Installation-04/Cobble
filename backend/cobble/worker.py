"""Background worker: logs the global event stream, runs the planner jobs and the scheduler.

Three loops share one process (the scheduler one only when the pack is configured).
The events loop only logs. The jobs loop reads `cobble:jobs`
(consumer group `workers`), runs each job to completion and acknowledges it afterwards. A job
whose worker died before the acknowledgement stays pending and is claimed again (XAUTOCLAIM)
at start-up and periodically, so it is resumed. A failed job publishes `job.failed` and is
acknowledged: nothing is retried forever. The scheduler loop (own thread) drives the building
projects: it reconciles at start-up, then ticks every `COBBLE_SCHEDULER_INTERVAL_S` seconds. The
`start` job (queued by `POST /projects/{id}/start`) is executed by the jobs loop.
"""

from __future__ import annotations

import json
import logging
import signal
import socket
import threading
import time
import uuid
from collections.abc import Callable
from types import FrameType
from typing import Any, cast

from redis import Redis
from redis.exceptions import RedisError, ResponseError

from cobble.config import Settings, get_settings
from cobble.db import make_engine, make_session_factory
from cobble.events import EVENTS_STREAM, JOBS_GROUP, JOBS_STREAM, publish_project
from cobble.orchestrator.service import PlannerService
from cobble.router.budget import BudgetService
from cobble.router.costs import CostRouter
from cobble.router.gateway import LiteLLMGateway
from cobble.scheduler import Scheduler
from cobble.scheduler.factory import build_scheduler, make_scheduler_supervisor
from cobble.scheduler.supervisor import SchedulerSupervisor, SchedulerUnavailable

GROUP = "workers"
BLOCK_MS = 1000
RECLAIM_IDLE_MS = 10 * 60 * 1000  # a job idle this long belongs to a dead worker
RECLAIM_EVERY_S = 60.0

log = logging.getLogger("cobble.worker")


def ensure_group(client: Redis) -> None:
    try:
        client.xgroup_create(EVENTS_STREAM, GROUP, id="$", mkstream=True)
    except ResponseError as exc:
        if "BUSYGROUP" not in str(exc):
            raise


def handle(fields: dict[Any, Any]) -> None:
    event_type = fields.get(b"type", b"?").decode()
    log.info("event %s", event_type)


def consume_once(
    client: Redis, consumer: str, handler: Callable[[dict[Any, Any]], None] = handle
) -> int:
    """Read and acknowledge one batch. Returns the number of events handled."""
    batches = cast(
        "list[Any]",
        client.xreadgroup(GROUP, consumer, {EVENTS_STREAM: ">"}, count=50, block=BLOCK_MS),
    )
    handled = 0
    for _stream, entries in batches or []:
        for entry_id, fields in entries:
            handler(fields)
            client.xack(EVENTS_STREAM, GROUP, entry_id)
            handled += 1
    return handled


def run(client: Redis, stop: threading.Event, consumer: str | None = None) -> None:
    name = consumer or socket.gethostname()
    ensure_group(client)
    while not stop.is_set():
        try:
            consume_once(client, name)
        except RedisError:
            log.warning("redis error, retrying", exc_info=True)
            stop.wait(2.0)


# --- jobs ---------------------------------------------------------------------------------

JobHandler = Callable[[dict[Any, Any]], None]


def build_planner(settings: Settings, redis: Redis) -> PlannerService:
    """Wire the planner to the real cost router (LiteLLM gateway + budget + role models)."""
    sessions = make_session_factory(make_engine(settings.database_url))
    gateway = LiteLLMGateway(settings.litellm_url, settings.litellm_key, sessions, redis)
    router = CostRouter(
        gateway, BudgetService(sessions, redis), settings.role_models, settings.default_model
    )
    return PlannerService(sessions, router, redis, settings)


def ensure_jobs_group(client: Redis) -> None:
    # id="0": jobs queued before the first worker started are not lost.
    try:
        client.xgroup_create(JOBS_STREAM, JOBS_GROUP, id="0", mkstream=True)
    except ResponseError as exc:
        if "BUSYGROUP" not in str(exc):
            raise


def make_job_handler(
    planner: PlannerService,
    scheduler: Scheduler | SchedulerSupervisor | None = None,
    events: Redis | None = None,
) -> JobHandler:
    def unavailable(kind: str, project_id: uuid.UUID) -> None:
        log.warning("%s job dropped: the scheduler is not configured", kind)
        if events is not None:
            publish_project(
                events, project_id, "job.failed", {"kind": kind, "code": "scheduler_unavailable"}
            )

    def handler(fields: dict[Any, Any]) -> None:
        try:
            job = json.loads(fields[b"job"])
            kind = str(job["kind"])
            project_id = uuid.UUID(str(job["project_id"]))
        except (KeyError, ValueError, TypeError):
            log.warning("dropping malformed job: %r", fields)
            return
        log.info("job %s for project %s", kind, project_id)
        if kind == "start":
            try:
                if scheduler is None:
                    raise SchedulerUnavailable
                scheduler.run_start_job(project_id)
            except SchedulerUnavailable:
                unavailable("start", project_id)
            return
        if kind == "revert":
            try:
                if scheduler is None:
                    raise SchedulerUnavailable
                scheduler.run_revert_job(project_id, str(job.get("ref", "")))
            except SchedulerUnavailable:
                unavailable("revert", project_id)
            return
        planner.run_job(
            kind, project_id, feedback=job.get("feedback"), message_id=job.get("message_id")
        )

    return handler


def _process(client: Redis, entries: list[Any], handler: JobHandler) -> int:
    handled = 0
    for entry_id, fields in entries:
        try:
            handler(fields)
        except Exception:
            # run_job reports its own failures; this is a bug. Drop the job rather than loop.
            log.exception("job handler crashed, dropping job %r", entry_id)
        client.xack(JOBS_STREAM, JOBS_GROUP, entry_id)
        handled += 1
    return handled


def consume_jobs_once(
    client: Redis, consumer: str, handler: JobHandler, block_ms: int = BLOCK_MS
) -> int:
    """Run the next queued job(s) and acknowledge each one after it completed."""
    batches = cast(
        "list[Any]",
        client.xreadgroup(JOBS_GROUP, consumer, {JOBS_STREAM: ">"}, count=1, block=block_ms),
    )
    handled = 0
    for _stream, entries in batches or []:
        handled += _process(client, entries, handler)
    return handled


def recover_pending(
    client: Redis, consumer: str, handler: JobHandler, min_idle_ms: int = RECLAIM_IDLE_MS
) -> int:
    """Claim jobs left pending by a dead worker and run them. Returns how many were run."""
    handled = 0
    cursor: Any = "0-0"
    while True:
        reply = client.xautoclaim(
            JOBS_STREAM, JOBS_GROUP, consumer, min_idle_ms, start_id=cursor, count=10
        )
        cursor, entries = reply[0], reply[1]
        handled += _process(client, [e for e in entries if e], handler)
        if cursor in (b"0-0", "0-0"):
            return handled


def run_jobs(
    client: Redis, stop: threading.Event, handler: JobHandler, consumer: str | None = None
) -> None:
    name = consumer or socket.gethostname()
    idle_ms = 0  # at start-up everything pending is ours to resume (single worker in v0.1)
    next_reclaim = 0.0
    while not stop.is_set():
        try:
            ensure_jobs_group(client)
            now = time.monotonic()
            if now >= next_reclaim:
                recover_pending(client, name, handler, idle_ms)
                idle_ms = RECLAIM_IDLE_MS
                next_reclaim = now + RECLAIM_EVERY_S
            consume_jobs_once(client, name, handler)
        except RedisError:
            log.warning("redis error in jobs loop, retrying", exc_info=True)
            stop.wait(2.0)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    stop = threading.Event()

    def _stop(_signum: int, _frame: FrameType | None) -> None:
        stop.set()

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    settings = get_settings()
    client = Redis.from_url(settings.redis_url)
    sessions = make_session_factory(make_engine(settings.database_url))
    scheduler: Scheduler | SchedulerSupervisor | None = make_scheduler_supervisor(
        settings, sessions, client
    ) or build_scheduler(settings, sessions, client)
    handler = make_job_handler(build_planner(settings, client), scheduler, client)
    threads = [threading.Thread(target=run_jobs, args=(client, stop, handler), name="jobs")]
    if scheduler is not None:
        threads.append(
            threading.Thread(target=scheduler.run_forever, args=(stop,), name="scheduler")
        )
    for thread in threads:
        thread.start()
    log.info("worker started")
    try:
        run(client, stop)
    finally:
        stop.set()
        for thread in threads:
            thread.join()
    log.info("worker stopped")


if __name__ == "__main__":
    main()
