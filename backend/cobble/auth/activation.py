"""One-use activation tokens for creating the first admin."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from enum import Enum

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from cobble.db import ActivationToken

from .tokens import aware, hash_token, new_token, utcnow

ACTIVATION_LIFETIME = timedelta(hours=24)


class TokenState(Enum):
    CONSUMED = "consumed"
    INVALID = "invalid"
    EXPIRED = "expired"


def create_activation_token(
    db: Session, now: datetime | None = None, user_id: uuid.UUID | None = None
) -> tuple[str, datetime]:
    """Create a one-use token. With `user_id` it is a reset link for that existing user."""
    now = now or utcnow()
    token = new_token()
    expires_at = now + ACTIVATION_LIFETIME
    db.add(ActivationToken(token_hash=hash_token(token), expires_at=expires_at, user_id=user_id))
    db.commit()
    return token, expires_at


def reset_target(db: Session, token: str, now: datetime | None = None) -> uuid.UUID | None:
    """The user a still-valid reset token points to, or None (not a reset / used / expired)."""
    now = now or utcnow()
    row = db.scalars(
        select(ActivationToken).where(ActivationToken.token_hash == hash_token(token))
    ).first()
    if row is None or row.user_id is None or row.used_at is not None:
        return None
    return row.user_id if aware(row.expires_at) > now else None


def consume_activation_token(db: Session, token: str, now: datetime | None = None) -> TokenState:
    """Atomically mark the token used. The caller commits (or rolls back) the transaction."""
    now = now or utcnow()
    digest = hash_token(token)
    row = db.scalars(select(ActivationToken).where(ActivationToken.token_hash == digest)).first()
    if row is None or row.used_at is not None:
        return TokenState.INVALID
    if aware(row.expires_at) <= now:
        return TokenState.EXPIRED
    result = db.execute(
        update(ActivationToken)
        .where(ActivationToken.id == row.id, ActivationToken.used_at.is_(None))
        .values(used_at=now)
    )
    if result.rowcount != 1:  # type: ignore[attr-defined]
        return TokenState.INVALID
    return TokenState.CONSUMED
