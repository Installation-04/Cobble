from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from redis.exceptions import RedisError
from sqlalchemy.orm import Session, sessionmaker

from cobble.api.app import create_app
from cobble.api.sse import SseOptions, event_stream, frame, start_id
from cobble.config import Settings
from cobble.events import project_stream, publish_project

from .fakes import FakeStreamRedis
from .planning import make_project
from .test_planning_api import API, client_for, owner_of

FAST = SseOptions(ping_s=15.0, block_ms=5, max_s=0.2)


def collect(redis: Any, stream: str, last_id: str, options: SseOptions = FAST) -> str:
    async def run() -> str:
        async def alive() -> bool:
            return False

        return "".join(
            [chunk async for chunk in event_stream(redis, stream, last_id, alive, options)]
        )

    return asyncio.run(run())


def seeded(pid: uuid.UUID) -> tuple[FakeStreamRedis, str]:
    redis = FakeStreamRedis()
    publish_project(redis, pid, "job.started", {"kind": "spec"})  # type: ignore[arg-type]
    publish_project(redis, pid, "spec.updated", {"version": 1})  # type: ignore[arg-type]
    publish_project(redis, pid, "phase.changed", {"phase": "spec_review"})  # type: ignore[arg-type]
    return redis, project_stream(pid)


def test_frame_format() -> None:
    text = frame("5-0", {b"type": b"spec.updated", b"payload": b'{"version": 1}'})
    assert text == 'id: 5-0\nevent: spec.updated\ndata: {"version": 1}\n\n'


def test_stream_delivers_events_in_order_with_their_ids() -> None:
    redis, stream = seeded(uuid.uuid4())
    text = collect(redis, stream, "0-0")
    assert text.startswith("retry: 3000\n\n")
    frames = [f for f in text.split("\n\n") if f.startswith("id:")]
    assert [f.splitlines()[1] for f in frames] == [
        "event: job.started",
        "event: spec.updated",
        "event: phase.changed",
    ]
    assert [f.splitlines()[0] for f in frames] == ["id: 1-0", "id: 2-0", "id: 3-0"]
    assert json.loads(frames[1].splitlines()[2].removeprefix("data: ")) == {"version": 1}


def test_stream_resumes_after_the_last_event_id() -> None:
    redis, stream = seeded(uuid.uuid4())
    text = collect(redis, stream, "2-0")
    assert "id: 3-0" in text
    assert "id: 1-0" not in text
    assert "id: 2-0" not in text


def test_stream_picks_up_events_published_while_waiting() -> None:
    redis = FakeStreamRedis()
    stream = "cobble:project:x:events"

    async def run() -> str:
        async def alive() -> bool:
            return False

        out: list[str] = []
        async for chunk in event_stream(
            redis, stream, "0-0", alive, SseOptions(block_ms=5, max_s=0.3)
        ):
            out.append(chunk)
            if chunk.startswith("retry"):
                redis.xadd(stream, {"type": "message.created", "payload": "{}"})
        return "".join(out)

    assert "event: message.created" in asyncio.run(run())


def test_ping_comment_is_sent_when_nothing_happens() -> None:
    text = collect(FakeStreamRedis(), "s", "0-0", SseOptions(ping_s=0.0, block_ms=5, max_s=0.1))
    assert ": ping\n\n" in text


def test_no_ping_before_the_interval() -> None:
    text = collect(FakeStreamRedis(), "s", "0-0", SseOptions(ping_s=60.0, block_ms=5, max_s=0.1))
    assert ": ping" not in text


def test_stream_ends_when_the_client_disconnects() -> None:
    calls = 0

    async def disconnected() -> bool:
        nonlocal calls
        calls += 1
        return calls > 2

    async def run() -> list[str]:
        options = SseOptions(block_ms=5, max_s=None)
        return [c async for c in event_stream(FakeStreamRedis(), "s", "0-0", disconnected, options)]

    chunks = asyncio.run(asyncio.wait_for(run(), timeout=5))
    assert chunks[0] == "retry: 3000\n\n"
    assert calls == 3


def test_stream_ends_cleanly_when_redis_fails() -> None:
    text = collect(FakeStreamRedis(fail=True), "s", "0-0")
    assert text == "retry: 3000\n\n"


def test_start_id_prefers_the_client_cursor_then_the_newest_entry() -> None:
    redis, stream = seeded(uuid.uuid4())
    assert start_id(redis, stream, "7-3", None) == "7-3"
    assert start_id(redis, stream, None, "4-0") == "4-0"
    assert start_id(redis, stream, "garbage", None) == "3-0"
    assert start_id(redis, stream, None, None) == "3-0"
    assert start_id(FakeStreamRedis(), "empty", None, None) == "0-0"


def test_start_id_propagates_redis_errors() -> None:
    with pytest.raises(RedisError):
        start_id(FakeStreamRedis(fail=True), "s", None, None)


# --- the HTTP endpoint ---------------------------------------------------------------------


@pytest.fixture
def stream_api(sessions: sessionmaker[Session]) -> tuple[TestClient, FakeStreamRedis, uuid.UUID]:
    pid = make_project(sessions)
    redis = FakeStreamRedis()
    api = client_for(sessions, redis, owner_of(sessions, pid))
    api.app.state.sse = SseOptions(ping_s=0.05, block_ms=5, max_s=0.3)  # type: ignore[attr-defined]
    return api, redis, pid


def seed_project(redis: FakeStreamRedis, pid: uuid.UUID) -> None:
    publish_project(redis, pid, "job.started", {"kind": "plan"})  # type: ignore[arg-type]
    publish_project(redis, pid, "plan.updated", {"version": 1})  # type: ignore[arg-type]


def test_endpoint_streams_with_the_right_headers_and_resumes(
    stream_api: tuple[TestClient, FakeStreamRedis, uuid.UUID],
) -> None:
    api, redis, pid = stream_api
    seed_project(redis, pid)
    reply = api.get(f"{API}/projects/{pid}/stream", headers={"Last-Event-ID": "1-0"})
    assert reply.status_code == 200
    assert reply.headers["content-type"].startswith("text/event-stream")
    assert reply.headers["cache-control"] == "no-cache"
    assert reply.headers["x-accel-buffering"] == "no"
    assert "id: 2-0\nevent: plan.updated\ndata: " in reply.text
    assert "job.started" not in reply.text
    assert ": ping" in reply.text


def test_endpoint_accepts_the_cursor_as_a_query_parameter(
    stream_api: tuple[TestClient, FakeStreamRedis, uuid.UUID],
) -> None:
    api, redis, pid = stream_api
    seed_project(redis, pid)
    reply = api.get(f"{API}/projects/{pid}/stream?last_event_id=0-0")
    assert "job.started" in reply.text
    assert "plan.updated" in reply.text


def test_endpoint_without_a_cursor_only_sends_new_events(
    stream_api: tuple[TestClient, FakeStreamRedis, uuid.UUID],
) -> None:
    api, redis, pid = stream_api
    seed_project(redis, pid)
    reply = api.get(f"{API}/projects/{pid}/stream")
    assert reply.status_code == 200
    assert "event:" not in reply.text


def test_endpoint_only_streams_its_own_project(
    stream_api: tuple[TestClient, FakeStreamRedis, uuid.UUID],
) -> None:
    api, redis, pid = stream_api
    publish_project(redis, uuid.uuid4(), "job.started", {"kind": "plan"})  # type: ignore[arg-type]
    reply = api.get(f"{API}/projects/{pid}/stream?last_event_id=0-0")
    assert "event:" not in reply.text


def test_endpoint_is_503_when_redis_is_down(sessions: sessionmaker[Session]) -> None:
    pid = make_project(sessions)
    api = client_for(sessions, FakeStreamRedis(fail=True), owner_of(sessions, pid))
    reply = api.get(f"{API}/projects/{pid}/stream")
    assert reply.status_code == 503


def test_app_has_default_sse_options(sessions: sessionmaker[Session]) -> None:
    app = create_app(
        {"database": lambda: None},
        settings=Settings(),
        session_factory=sessions,
        redis=FakeStreamRedis(),
    )
    assert getattr(app.state, "sse", None) is None  # the route falls back to SseOptions()
    assert SseOptions().ping_s == 15.0
