from __future__ import annotations

import json
from typing import Any

from cobble.events import EVENTS_STREAM, publish
from cobble.worker import consume_once

from .fakes import FakeRedis


def test_publish_appends_typed_event() -> None:
    redis = FakeRedis()
    entry = publish(redis, "budget.reached", {"project": "p1"})  # type: ignore[arg-type]
    assert entry == "1-0"
    stream, fields = redis.added[0]
    assert stream == EVENTS_STREAM
    assert fields["type"] == "budget.reached"
    assert json.loads(fields["payload"]) == {"project": "p1"}


def test_publish_never_raises_when_redis_is_down() -> None:
    assert publish(FakeRedis(fail=True), "x", {}) is None  # type: ignore[arg-type]


def test_worker_handles_and_acknowledges() -> None:
    redis = FakeRedis()
    redis.pending = [(b"1-0", {b"type": b"a"}), (b"2-0", {b"type": b"b"})]
    seen: list[Any] = []
    handled = consume_once(redis, "w1", seen.append)  # type: ignore[arg-type]
    assert handled == 2
    assert [f[b"type"] for f in seen] == [b"a", b"b"]
    assert redis.acked == [b"1-0", b"2-0"]
    assert consume_once(redis, "w1", seen.append) == 0  # type: ignore[arg-type]
