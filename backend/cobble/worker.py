"""Background worker: logs the global event stream, runs the planner jobs and the scheduler.

Three loops share one process (the scheduler one only when the pack is configured).
The events loop only logs. The jobs loop reads `cobble:jobs`
(consumer group `workers`), runs each job to completion and acknowledges it afterwards. A job
whose worker died before the acknowledgement stays pending and is claimed again (XCLAIM): at
start-up the entries of this very consumer (its name is stable, see `consumer_name`), at every
tick the ones whose owner has been silent for `RECLAIM_IDLE_MS`, so a live peer's jobs are never
stolen. A job that fails is reported by the planner (`job.failed`) and acknowledged. A handler
that crashes (a bug) leaves the job pending for a retry; after `MAX_DELIVERIES` deliveries the
job goes to the dead-letter stream `cobble:jobs:dead`, a `job.failed` event with the code
`crashed` is published and the job is acknowledged: nothing is retried forever (ADR 0016). The
scheduler loop (own thread) drives the building
projects: it reconciles at start-up, then ticks every `COBBLE_SCHEDULER_INTERVAL_S` seconds. The
`start` job (queued by `POST /projects/{id}/start`) is executed by the jobs loop.
"""

from __future__ import annotations

import json
import logging
import os
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
from cobble.router.factory import build_cost_router
from cobble.scheduler import Scheduler
from cobble.scheduler.factory import build_scheduler, make_scheduler_supervisor
from cobble.scheduler.supervisor import SchedulerSupervisor, SchedulerUnavailable

GROUP = "workers"
BLOCK_MS = 1000
RECLAIM_IDLE_MS = 10 * 60 * 1000  # a job of ANOTHER consumer idle this long belongs to a dead one
RETRY_DELAY_MS = 30 * 1000  # a crashed job of this consumer is retried after this delay
RECLAIM_EVERY_S = 60.0
MAX_DELIVERIES = 3  # deliveries before a job that keeps failing is dead-lettered
DEAD_STREAM = "cobble:jobs:dead"
DEAD_STREAM_LENGTH = 1000
ERROR_CHARS = 300

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
    """Wire the planner to the real cost router (LiteLLM gateway + budget + role routes)."""
    sessions = make_session_factory(make_engine(settings.database_url))
    router = build_cost_router(settings, sessions, redis)
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
        if kind == "explain":
            planner.run_job(
                kind, project_id, ref=str(job.get("ref", "")), force=bool(job.get("force"))
            )
            return
        planner.run_job(
            kind, project_id, feedback=job.get("feedback"), message_id=job.get("message_id")
        )

    return handler


def consumer_name() -> str:
    """Stable per container (a restart keeps it), so a restarted worker finds its own jobs.
    `COBBLE_WORKER_NAME` overrides it; two live workers must never share a name."""
    return os.environ.get("COBBLE_WORKER_NAME") or socket.gethostname()


def _text(value: Any) -> str:
    return value.decode() if isinstance(value, bytes) else str(value)


def _deliveries(client: Redis, entry_id: Any) -> int:
    rows = cast("list[Any]", client.xpending_range(JOBS_STREAM, JOBS_GROUP, entry_id, entry_id, 1))
    return int(rows[0]["times_delivered"]) if rows else 1


def _dead_letter(
    client: Redis, entry_id: Any, fields: dict[Any, Any], deliveries: int, why: str
) -> None:
    """Park a job that keeps failing where the owner can see it, and tell the project."""
    raw = fields.get(b"job", b"")
    job = raw.decode(errors="replace") if isinstance(raw, bytes) else str(raw)
    log.error("job %r dead-lettered after %d deliveries: %s", entry_id, deliveries, why)
    client.xadd(
        DEAD_STREAM,
        {
            "job": job[:2000],
            "entry_id": _text(entry_id),
            "deliveries": str(deliveries),
            "error": why[:ERROR_CHARS],
        },
        maxlen=DEAD_STREAM_LENGTH,
        approximate=True,
    )
    try:
        data = json.loads(job)
        publish_project(
            client,
            uuid.UUID(str(data["project_id"])),
            "job.failed",
            {"kind": str(data["kind"]), "code": "crashed"},
        )
    except (KeyError, ValueError, TypeError):
        pass  # malformed jobs are dropped earlier; nothing to tell


def _process(client: Redis, entries: list[Any], handler: JobHandler) -> int:
    """Run each entry; acknowledge it unless its handler crashed and a retry is still allowed.
    Returns the number of entries acknowledged."""
    done = 0
    for entry_id, fields in entries:
        try:
            handler(fields)
        except Exception as exc:
            # run_job reports its own failures; reaching here is a bug.
            log.exception("job handler crashed, job %r", entry_id)
            deliveries = _deliveries(client, entry_id)
            if deliveries < MAX_DELIVERIES:
                log.warning("job %r stays pending for a retry (delivery %d)", entry_id, deliveries)
                continue
            _dead_letter(client, entry_id, fields, deliveries, f"{type(exc).__name__}: {exc}")
        client.xack(JOBS_STREAM, JOBS_GROUP, entry_id)
        done += 1
    return done


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
    client: Redis,
    consumer: str,
    handler: JobHandler,
    min_idle_ms: int = RECLAIM_IDLE_MS,
    own_idle_ms: int | None = None,
) -> int:
    """Claim the pending jobs nobody is running and run them. Returns how many were settled.

    An entry of another consumer is taken once idle for `min_idle_ms` (its worker is presumed
    dead); an entry of `consumer` itself once idle for `own_idle_ms` (default `min_idle_ms`): 0
    at start-up, since this process is the only one that can be running it. A job already
    delivered `MAX_DELIVERIES` times without being acknowledged (it keeps killing its worker)
    is dead-lettered instead of run.
    """
    own = min_idle_ms if own_idle_ms is None else own_idle_ms
    rows = cast("list[Any]", client.xpending_range(JOBS_STREAM, JOBS_GROUP, "-", "+", 100))
    handled = 0
    for row in rows:
        threshold = own if _text(row["consumer"]) == consumer else min_idle_ms
        if int(row["time_since_delivered"]) < threshold:
            continue
        claimed = cast(
            "list[Any]",
            client.xclaim(JOBS_STREAM, JOBS_GROUP, consumer, threshold, [row["message_id"]]),
        )
        entries = [entry for entry in claimed if entry and entry[1]]
        if int(row["times_delivered"]) >= MAX_DELIVERIES:
            for entry_id, fields in entries:
                times = int(row["times_delivered"])
                _dead_letter(client, entry_id, fields, times, "worker died repeatedly")
                client.xack(JOBS_STREAM, JOBS_GROUP, entry_id)
                handled += 1
            continue
        handled += _process(client, entries, handler)
    return handled


def run_jobs(
    client: Redis, stop: threading.Event, handler: JobHandler, consumer: str | None = None
) -> None:
    name = consumer or consumer_name()
    own_idle_ms = 0  # at start-up our own pending jobs are ours to resume at once
    next_reclaim = 0.0
    while not stop.is_set():
        try:
            ensure_jobs_group(client)
            now = time.monotonic()
            if now >= next_reclaim:
                recover_pending(client, name, handler, RECLAIM_IDLE_MS, own_idle_ms)
                own_idle_ms = RETRY_DELAY_MS
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
