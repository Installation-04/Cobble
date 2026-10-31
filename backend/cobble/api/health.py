"""Health endpoint."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Literal

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel

import cobble

log = logging.getLogger(__name__)
router = APIRouter()

Check = Callable[[], None]
Status = Literal["ok", "error"]


class HealthResponse(BaseModel):
    status: Status
    database: Status
    redis: Status
    version: str
    pack_mode: Literal["real", "fake"]


def _run(check: Check, name: str) -> Status:
    try:
        check()
    except Exception:
        log.warning("health check failed: %s", name, exc_info=True)
        return "error"
    return "ok"


@router.get("/health", response_model=HealthResponse)
def health(request: Request, response: Response) -> HealthResponse:
    checks: dict[str, Check] = request.app.state.checks
    database = _run(checks["database"], "database")
    redis = _run(checks["redis"], "redis")
    healthy = database == "ok" and redis == "ok"
    if not healthy:
        response.status_code = 503
    return HealthResponse(
        status="ok" if healthy else "error",
        database=database,
        redis=redis,
        version=cobble.__version__,
        pack_mode=request.app.state.settings.pack_mode,
    )
