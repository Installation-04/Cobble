"""Background worker. In step 2 it only consumes the event stream and logs it."""

from __future__ import annotations

import logging
import signal
import socket
import threading
from collections.abc import Callable
from types import FrameType
from typing import Any, cast

from redis import Redis
from redis.exceptions import RedisError, ResponseError

from cobble.config import get_settings
from cobble.events import EVENTS_STREAM

GROUP = "workers"
BLOCK_MS = 1000

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


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    stop = threading.Event()

    def _stop(_signum: int, _frame: FrameType | None) -> None:
        stop.set()

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    log.info("worker started")
    run(Redis.from_url(get_settings().redis_url), stop)
    log.info("worker stopped")


if __name__ == "__main__":
    main()
