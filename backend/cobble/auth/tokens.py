"""Opaque random tokens; only their SHA-256 is ever stored."""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime


def new_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def utcnow() -> datetime:
    return datetime.now(UTC)


def aware(value: datetime) -> datetime:
    """Treat naive datetimes (SQLite) as UTC."""
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
