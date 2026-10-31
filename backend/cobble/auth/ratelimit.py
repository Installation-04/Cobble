"""Login brute-force protection: 5 failures per email+IP in 15 minutes."""

from __future__ import annotations

import logging
from typing import Any

from redis.exceptions import RedisError

from .tokens import hash_token

log = logging.getLogger(__name__)

MAX_FAILURES = 5
WINDOW_SECONDS = 15 * 60


def _key(email: str, ip: str) -> str:
    return f"cobble:login_failures:{hash_token(email)}:{ip}"


def is_blocked(redis: Any, email: str, ip: str) -> bool:
    try:
        value = redis.get(_key(email, ip))
        return value is not None and int(value) >= MAX_FAILURES
    except (RedisError, OSError):
        log.warning("login rate limit unavailable (redis down); failing open", exc_info=True)
        return False


def record_failure(redis: Any, email: str, ip: str) -> None:
    key = _key(email, ip)
    try:
        count = int(redis.incr(key))
        if count == 1:
            redis.expire(key, WINDOW_SECONDS)
    except (RedisError, OSError):
        log.warning("login rate limit unavailable (redis down); failing open", exc_info=True)


def reset(redis: Any, email: str, ip: str) -> None:
    try:
        redis.delete(_key(email, ip))
    except (RedisError, OSError):
        log.warning("login rate limit unavailable (redis down); failing open", exc_info=True)
