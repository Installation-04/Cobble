"""Shared request dependencies."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import Annotated, Any

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from cobble.auth.sessions import user_for_token
from cobble.config import Settings
from cobble.db import Project, User

from .errors import ApiError

COOKIE_NAME = "cobble_session"


def get_db(request: Request) -> Iterator[Session]:
    with request.app.state.session_factory() as session:
        yield session


def get_settings_dep(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_redis(request: Request) -> Any:
    return request.app.state.redis


def current_user(request: Request, db: Annotated[Session, Depends(get_db)]) -> User:
    token = request.cookies.get(COOKIE_NAME)
    user = user_for_token(db, token) if token else None
    if user is None:
        raise ApiError(401, "unauthenticated")
    return user


def admin_user(user: Annotated[User, Depends(current_user)]) -> User:
    """Modules are global and the most privileged action of the product: administrators only."""
    if user.role != "admin":
        raise ApiError(403, "forbidden")
    return user


Db = Annotated[Session, Depends(get_db)]
CurrentUser = Annotated[User, Depends(current_user)]
AdminUser = Annotated[User, Depends(admin_user)]
AppSettings = Annotated[Settings, Depends(get_settings_dep)]
RedisDep = Annotated[Any, Depends(get_redis)]


def parse_id(value: str) -> uuid.UUID:
    """Path ids that are not UUIDs cannot exist: answer 404, not 422."""
    try:
        return uuid.UUID(value)
    except ValueError:
        raise ApiError(404, "not_found") from None


def owned_project(project_id: str, user: CurrentUser, db: Db) -> Project:
    """The project of the path, if it belongs to the authenticated user (404 otherwise)."""
    project = db.scalars(
        select(Project).where(Project.id == parse_id(project_id), Project.owner_id == user.id)
    ).first()
    if project is None:
        raise ApiError(404, "not_found")
    return project


OwnedProject = Annotated[Project, Depends(owned_project)]
