"""FastAPI application factory."""

from __future__ import annotations

from fastapi import FastAPI
from redis import Redis
from sqlalchemy import text

from cobble.config import Settings, get_settings
from cobble.db import make_engine

from .health import Check
from .health import router as health_router


def default_checks(settings: Settings) -> dict[str, Check]:
    engine = make_engine(settings.database_url)
    redis = Redis.from_url(settings.redis_url)

    def database() -> None:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))

    def redis_ping() -> None:
        redis.ping()

    return {"database": database, "redis": redis_ping}


def create_app(checks: dict[str, Check] | None = None) -> FastAPI:
    app = FastAPI(
        title="Cobble",
        openapi_url="/api/v1/openapi.json",
        docs_url="/api/v1/docs",
        redoc_url=None,
    )
    app.state.checks = checks if checks is not None else default_checks(get_settings())
    app.include_router(health_router, prefix="/api/v1")
    return app
