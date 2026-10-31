"""Login sessions: the cookie holds a token, the database its SHA-256."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from cobble.db import AuthSession, User

from .tokens import aware, hash_token, new_token, utcnow

SESSION_LIFETIME = timedelta(days=7)


def create_session(db: Session, user_id: uuid.UUID, now: datetime | None = None) -> str:
    now = now or utcnow()
    token = new_token()
    db.add(
        AuthSession(
            user_id=user_id, token_hash=hash_token(token), expires_at=now + SESSION_LIFETIME
        )
    )
    db.commit()
    return token


def user_for_token(db: Session, token: str, now: datetime | None = None) -> User | None:
    """Return the session's user and extend the session, or None if unknown/expired."""
    now = now or utcnow()
    row = db.scalars(select(AuthSession).where(AuthSession.token_hash == hash_token(token))).first()
    if row is None:
        return None
    if aware(row.expires_at) <= now:
        db.delete(row)
        db.commit()
        return None
    user = db.get(User, row.user_id)
    if user is None:
        return None
    row.expires_at = now + SESSION_LIFETIME
    db.commit()
    return user


def delete_session(db: Session, token: str) -> None:
    db.execute(delete(AuthSession).where(AuthSession.token_hash == hash_token(token)))
    db.commit()
