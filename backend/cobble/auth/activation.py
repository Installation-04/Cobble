"""One-use activation tokens for creating the first admin."""

from __future__ import annotations

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


def create_activation_token(db: Session, now: datetime | None = None) -> tuple[str, datetime]:
    now = now or utcnow()
    token = new_token()
    expires_at = now + ACTIVATION_LIFETIME
    db.add(ActivationToken(token_hash=hash_token(token), expires_at=expires_at))
    db.commit()
    return token, expires_at


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
