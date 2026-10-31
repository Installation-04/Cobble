"""Event bus on Redis streams. Every state change publishes an event."""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from redis import Redis
from redis.exceptions import RedisError

EVENTS_STREAM = "cobble:events"
MAX_STREAM_LENGTH = 10_000

log = logging.getLogger(__name__)


def publish(client: Redis, event_type: str, payload: dict[str, Any]) -> str | None:
    """Append an event to the stream. Returns the entry id, or None if Redis is down.

    Publishing must never break the operation that produced the event.
    """
    try:
        entry_id = client.xadd(
            EVENTS_STREAM,
            {"type": event_type, "payload": json.dumps(payload, default=str)},
            maxlen=MAX_STREAM_LENGTH,
            approximate=True,
        )
    except RedisError:
        log.warning("could not publish event %s", event_type, exc_info=True)
        return None
    return entry_id.decode() if isinstance(entry_id, bytes) else str(entry_id)


# --- per-project events (server-sent to the UI) and background jobs -----------------------

JOBS_STREAM = "cobble:jobs"
JOBS_GROUP = "workers"
PROJECT_STREAM_LENGTH = 1_000


def project_stream(project_id: uuid.UUID | str) -> str:
    return f"cobble:project:{project_id}:events"


def _entry_id(raw: Any) -> str:
    return raw.decode() if isinstance(raw, bytes) else str(raw)


def publish_project(
    client: Redis, project_id: uuid.UUID | str, event_type: str, payload: dict[str, Any]
) -> str | None:
    """Append an event to the project's stream. Never raises (like `publish`)."""
    try:
        entry_id = client.xadd(
            project_stream(project_id),
            {"type": event_type, "payload": json.dumps(payload, default=str)},
            maxlen=PROJECT_STREAM_LENGTH,
            approximate=True,
        )
    except RedisError:
        log.warning("could not publish project event %s", event_type, exc_info=True)
        return None
    return _entry_id(entry_id)


def enqueue_job(client: Redis, kind: str, project_id: uuid.UUID | str, **extra: Any) -> str:
    """Queue a background job (`reply`, `spec` or `plan`). Raises RedisError if Redis is down."""
    job = {"kind": kind, "project_id": str(project_id), **extra}
    return _entry_id(client.xadd(JOBS_STREAM, {"job": json.dumps(job, default=str)}))
