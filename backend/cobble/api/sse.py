"""Server-sent events over a project's Redis stream.

The generator reads with XREAD BLOCK on the sync Redis client, in a worker thread, so a
connection costs one thread only while it waits. `id:` is the Redis stream id, so a browser
that reconnects sends `Last-Event-ID` and resumes without losing or repeating events.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from redis.exceptions import RedisError

log = logging.getLogger(__name__)

_STREAM_ID = re.compile(r"^\d+(-\d+)?$")

SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",  # tell proxies not to buffer the stream
    "Connection": "keep-alive",
}


@dataclass
class SseOptions:
    ping_s: float = 15.0
    block_ms: int = 1000
    max_s: float | None = None  # close after this long (the browser reconnects); None = never


def _text(value: Any) -> str:
    return value.decode() if isinstance(value, bytes) else str(value)


def start_id(client: Any, stream: str, header: str | None, query: str | None) -> str:
    """Where to resume: the client's last seen id, else just after the newest entry."""
    for candidate in (header, query):
        if candidate and _STREAM_ID.match(candidate):
            return candidate
    newest = client.xrevrange(stream, count=1)
    return _text(newest[0][0]) if newest else "0-0"


def frame(entry_id: str, fields: dict[Any, Any]) -> str:
    event = _text(fields.get(b"type", fields.get("type", "message")))
    data = _text(fields.get(b"payload", fields.get("payload", "{}")))
    return f"id: {entry_id}\nevent: {event}\ndata: {data}\n\n"


async def event_stream(
    client: Any,
    stream: str,
    last_id: str,
    is_disconnected: Callable[[], Awaitable[bool]],
    options: SseOptions,
) -> AsyncIterator[str]:
    started = last_sent = time.monotonic()
    yield "retry: 3000\n\n"
    while not await is_disconnected():
        if options.max_s is not None and time.monotonic() - started >= options.max_s:
            return
        try:
            batches = await asyncio.to_thread(
                client.xread, {stream: last_id}, count=100, block=options.block_ms
            )
        except RedisError:
            log.warning("redis error in event stream, closing", exc_info=True)
            return  # EventSource reconnects with Last-Event-ID
        for _name, entries in batches or []:
            for entry_id, fields in entries:
                last_id = _text(entry_id)
                yield frame(last_id, fields)
                last_sent = time.monotonic()
        if time.monotonic() - last_sent >= options.ping_s:
            yield ": ping\n\n"
            last_sent = time.monotonic()
