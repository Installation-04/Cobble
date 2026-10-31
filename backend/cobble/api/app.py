"""FastAPI application factory."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import FastAPI, Request, Response
from redis import Redis
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from cobble.config import Settings, get_settings
from cobble.db import make_engine, make_session_factory

from . import (
    routes_agents,
    routes_auth,
    routes_costs,
    routes_demo,
    routes_folders,
    routes_internal_llm,
    routes_planning,
    routes_projects,
    routes_tasks,
)
from .errors import error_response, install_error_handlers
from .health import Check
from .health import router as health_router

UNSAFE_METHODS = frozenset({"POST", "PATCH", "PUT", "DELETE"})
CSRF_HEADER = "x-requested-with"
CSRF_VALUE = "cobble"


def default_checks(
    settings: Settings,
    session_factory: sessionmaker[Session] | None = None,
    redis: Any = None,
) -> dict[str, Check]:
    sessions = session_factory or make_session_factory(make_engine(settings.database_url))
    client = redis if redis is not None else Redis.from_url(settings.redis_url)

    def database() -> None:
        with sessions() as session:
            session.execute(text("SELECT 1"))

    def redis_ping() -> None:
        client.ping()

    return {"database": database, "redis": redis_ping}


def create_app(
    checks: dict[str, Check] | None = None,
    *,
    settings: Settings | None = None,
    session_factory: sessionmaker[Session] | None = None,
    redis: Any = None,
) -> FastAPI:
    settings = settings or get_settings()
    session_factory = session_factory or make_session_factory(make_engine(settings.database_url))
    redis = redis if redis is not None else Redis.from_url(settings.redis_url)

    app = FastAPI(
        title="Cobble",
        openapi_url="/api/v1/openapi.json",
        docs_url="/api/v1/docs",
        redoc_url=None,
    )
    app.state.settings = settings
    app.state.session_factory = session_factory
    app.state.redis = redis
    app.state.checks = (
        checks if checks is not None else default_checks(settings, session_factory, redis)
    )

    @app.middleware("http")
    async def csrf_guard(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        # /internal/* uses bearer tokens (no cookies), so CSRF does not apply to it.
        internal = request.url.path.startswith("/internal/")
        if (
            request.method in UNSAFE_METHODS
            and not internal
            and request.headers.get(CSRF_HEADER) != CSRF_VALUE
        ):
            return error_response(403, "csrf_failed")
        return await call_next(request)

    install_error_handlers(app)
    app.include_router(health_router, prefix="/api/v1")
    for router in (
        routes_auth.router,
        routes_folders.router,
        routes_projects.router,
        routes_planning.router,
        routes_tasks.router,
        routes_agents.router,
        routes_costs.router,
        routes_demo.router,
    ):
        app.include_router(router, prefix="/api/v1")
    app.include_router(routes_internal_llm.router)
    if settings.pack_mode == "fake":
        # The API and the worker are two processes: the fake services keep no state, so an
        # instance here answers like the worker's (logs, diff of a run the worker started).
        from cobble.scheduler.fakepack import build_fake_services

        from . import routes_fakedemo

        fake = build_fake_services(settings)
        app.state.agents = fake.agents
        app.state.git = fake.git
        app.state.preview = fake.preview
        app.include_router(routes_fakedemo.router)  # /demo/... served by the API itself
    return app
