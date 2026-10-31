"""Tiny in-memory stand-ins used by unit tests."""

from __future__ import annotations

import time
from typing import Any

from redis.exceptions import RedisError, ResponseError


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


def _num(entry_id: str) -> tuple[int, int]:
    major, _, minor = entry_id.partition("-")
    return int(major), int(minor or 0)


class FakeStreamRedis:
    """In-memory Redis streams with consumer groups: XADD, XREAD, XREADGROUP, XAUTOCLAIM..."""

    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.streams: dict[str, list[tuple[str, dict[bytes, bytes]]]] = {}
        self.groups: dict[tuple[str, str], int] = {}  # next index to deliver
        self.pending: dict[tuple[str, str], dict[str, tuple[str, dict[bytes, bytes]]]] = {}
        self.acked: list[str] = []
        self._counter = 0

    def _check(self) -> None:
        if self.fail:
            raise RedisError("down")

    def xadd(self, stream: str, fields: dict[str, str], **_kw: Any) -> bytes:
        self._check()
        self._counter += 1
        entry_id = f"{self._counter}-0"
        stored = {k.encode(): v.encode() for k, v in fields.items()}
        self.streams.setdefault(stream, []).append((entry_id, stored))
        return entry_id.encode()

    def entries(self, stream: str) -> list[dict[str, Any]]:
        """Decoded fields of every entry of a stream, oldest first."""
        return [
            {k.decode(): v.decode() for k, v in fields.items()}
            for _id, fields in self.streams.get(stream, [])
        ]

    def xrevrange(self, stream: str, count: int | None = None) -> list[Any]:
        self._check()
        rows = [(i.encode(), f) for i, f in reversed(self.streams.get(stream, []))]
        return rows[:count] if count else rows

    def xread(self, streams: dict[str, str], count: int | None = None, block: int = 0) -> list[Any]:
        self._check()
        out: list[Any] = []
        for name, last in streams.items():
            rows = [(i.encode(), f) for i, f in self.streams.get(name, []) if _num(i) > _num(last)]
            if rows:
                out.append((name.encode(), rows[:count] if count else rows))
        if not out and block:
            time.sleep(min(block, 20) / 1000)
        return out

    def xgroup_create(self, stream: str, group: str, id: str = "$", mkstream: bool = False) -> bool:
        self._check()
        if (stream, group) in self.groups:
            raise ResponseError("BUSYGROUP Consumer Group name already exists")
        if stream not in self.streams and not mkstream:
            raise ResponseError("no such key")
        entries = self.streams.setdefault(stream, [])
        self.groups[(stream, group)] = 0 if id == "0" else len(entries)
        self.pending[(stream, group)] = {}
        return True

    def xreadgroup(
        self,
        group: str,
        consumer: str,
        streams: dict[str, str],
        count: int | None = None,
        block: int = 0,
    ) -> list[Any]:
        self._check()
        out: list[Any] = []
        for name in streams:
            entries = self.streams.get(name, [])
            start = self.groups[(name, group)]
            take = entries[start : start + count] if count else entries[start:]
            self.groups[(name, group)] = start + len(take)
            for entry_id, fields in take:
                self.pending[(name, group)][entry_id] = (consumer, fields)
            if take:
                out.append((name.encode(), [(i.encode(), f) for i, f in take]))
        if not out and block:
            time.sleep(min(block, 20) / 1000)
        return out

    def xack(self, stream: str, group: str, entry_id: Any) -> int:
        self._check()
        key = entry_id.decode() if isinstance(entry_id, bytes) else str(entry_id)
        self.acked.append(key)
        return 1 if self.pending[(stream, group)].pop(key, None) else 0

    def xautoclaim(
        self,
        stream: str,
        group: str,
        consumer: str,
        min_idle_time: int,
        start_id: str = "0-0",
        count: int | None = None,
    ) -> list[Any]:
        self._check()
        rows = sorted(self.pending[(stream, group)].items(), key=lambda kv: _num(kv[0]))
        claimed = [(i, v) for i, v in rows if _num(i) >= _num(start_id)]
        if count:
            claimed = claimed[:count]
        for entry_id, (_owner, fields) in claimed:
            self.pending[(stream, group)][entry_id] = (consumer, fields)
        return [b"0-0", [(i.encode(), v[1]) for i, v in claimed], []]
