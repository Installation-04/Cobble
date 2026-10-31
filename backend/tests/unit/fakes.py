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


class CounterRedis:
    """Counters with expiry bookkeeping, enough for the login rate limit."""

    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.values: dict[str, int] = {}
        self.ttl: dict[str, int] = {}

    def _check(self) -> None:
        if self.fail:
            raise RedisError("down")

    def get(self, key: str) -> bytes | None:
        self._check()
        return str(self.values[key]).encode() if key in self.values else None

    def incr(self, key: str) -> int:
        self._check()
        self.values[key] = self.values.get(key, 0) + 1
        return self.values[key]

    def expire(self, key: str, seconds: int) -> bool:
        self._check()
        self.ttl[key] = seconds
        return True

    def delete(self, key: str) -> int:
        self._check()
        self.ttl.pop(key, None)
        return 1 if self.values.pop(key, None) is not None else 0

    def ping(self) -> bool:
        self._check()
        return True
