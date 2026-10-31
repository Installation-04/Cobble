"""Event bus on Redis streams. Every state change publishes an event."""

from __future__ import annotations

import json
import logging
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
