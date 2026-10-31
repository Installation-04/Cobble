"""Tiny in-memory stand-ins used by unit tests."""

from __future__ import annotations

from typing import Any

from redis.exceptions import RedisError


class FakeRedis:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.added: list[tuple[str, dict[str, str]]] = []
        self.acked: list[Any] = []
        self.pending: list[Any] = []

    def xadd(self, stream: str, fields: dict[str, str], **_kw: Any) -> bytes:
        if self.fail:
            raise RedisError("down")
        self.added.append((stream, fields))
        return b"1-0"

    def xreadgroup(self, *_a: Any, **_kw: Any) -> list[Any]:
        batch, self.pending = self.pending, []
        return [(b"cobble:events", batch)] if batch else []

    def xack(self, _stream: str, _group: str, entry_id: Any) -> int:
        self.acked.append(entry_id)
        return 1
