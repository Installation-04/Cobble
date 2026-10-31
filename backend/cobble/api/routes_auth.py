"""Setup status and authentication endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Request, Response
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError

from cobble.auth import ratelimit
from cobble.auth.activation import TokenState, consume_activation_token, reset_target
from cobble.auth.passwords import burn_verification, hash_password, verify_password
from cobble.auth.sessions import SESSION_LIFETIME, create_session, delete_session
from cobble.db import AuthSession, User

from .deps import COOKIE_NAME, AppSettings, CurrentUser, Db, RedisDep
from .errors import ApiError
from .schemas import ActivateIn, LoginIn, MePatch, SetupStatus, UserOut

router = APIRouter()


def _user_count(db: Db) -> int:
    return int(db.scalar(select(func.count()).select_from(User)) or 0)


def _set_cookie(response: Response, settings: AppSettings, token: str) -> None:
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=int(SESSION_LIFETIME.total_seconds()),
        path="/",
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
    )


@router.get("/setup/status", response_model=SetupStatus)
def setup_status(db: Db) -> SetupStatus:
    return SetupStatus(initialized=_user_count(db) > 0)


@router.post("/auth/activate", status_code=201, response_model=UserOut)
def activate(body: ActivateIn, response: Response, db: Db, settings: AppSettings) -> User:
    target = reset_target(db, body.token)
    if target is not None:
        return _reset_admin(body, target, response, db, settings)
    if _user_count(db) > 0:
        raise ApiError(409, "already_initialized")
    state = consume_activation_token(db, body.token)
    if state is TokenState.EXPIRED:
        raise ApiError(410, "activation_expired")
    if state is TokenState.INVALID:
        raise ApiError(400, "activation_invalid")
    user = User(
        email=body.email,
        password_hash=hash_password(body.password),
        lang=body.lang or "en",
    )
    db.add(user)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise ApiError(409, "already_initialized") from None
    if _user_count(db) > 1:  # lost a race with a concurrent activation
        db.rollback()
        raise ApiError(409, "already_initialized")
    db.commit()
    _set_cookie(response, settings, create_session(db, user.id))
    return user


def _reset_admin(
    body: ActivateIn, user_id: uuid.UUID, response: Response, db: Db, settings: AppSettings
) -> User:
    """A reset link changes the admin's email and password and keeps all their data."""
    if consume_activation_token(db, body.token) is not TokenState.CONSUMED:
        raise ApiError(400, "activation_invalid")
    user = db.get(User, user_id)
    if user is None:
        raise ApiError(400, "activation_invalid")
    user.email = body.email
    user.password_hash = hash_password(body.password)
    if body.lang:
        user.lang = body.lang
    db.execute(delete(AuthSession).where(AuthSession.user_id == user.id))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise ApiError(409, "already_initialized") from None
    _set_cookie(response, settings, create_session(db, user.id))
    return user


@router.post("/auth/login", response_model=UserOut)
def login(
    body: LoginIn,
    request: Request,
    response: Response,
    db: Db,
    settings: AppSettings,
    redis: RedisDep,
) -> User:
    ip = request.client.host if request.client else "unknown"
    if ratelimit.is_blocked(redis, body.email, ip):
        raise ApiError(429, "too_many_attempts")
    user = db.scalars(select(User).where(User.email == body.email)).first()
    if user is None:
        burn_verification()
    if user is None or not verify_password(body.password, user.password_hash):
        ratelimit.record_failure(redis, body.email, ip)
        raise ApiError(401, "invalid_credentials")
    ratelimit.reset(redis, body.email, ip)
    _set_cookie(response, settings, create_session(db, user.id))
    return user


@router.post("/auth/logout", status_code=204)
def logout(request: Request, db: Db, settings: AppSettings) -> Response:
    token = request.cookies.get(COOKIE_NAME)
    if token:
        delete_session(db, token)
    response = Response(status_code=204)
    response.delete_cookie(
        COOKIE_NAME, path="/", httponly=True, samesite="lax", secure=settings.cookie_secure
    )
    return response


@router.get("/auth/me", response_model=UserOut)
def me(user: CurrentUser) -> User:
    return user


@router.patch("/auth/me", response_model=UserOut)
def update_me(body: MePatch, user: CurrentUser, db: Db) -> User:
    if body.lang is not None:
        user.lang = body.lang
    if body.theme is not None:
        user.theme = body.theme
    db.commit()
    return user
