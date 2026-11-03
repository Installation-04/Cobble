"""FastAPI application: the agent-service HTTP API (ADR 0006)."""

from __future__ import annotations

import hmac
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .config import Settings
from .engine import ContainerEngine, DockerEngine
from .gitops import GitOps
from .models import RunCreated, RunRequest, RunStatus
from .runs import RunError, RunManager


def _error(status: int, code: str, params: dict[str, Any] | None = None) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "params": params or {}}}, status_code=status)


def create_app(settings: Settings | None = None, engine: ContainerEngine | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    engine = engine or DockerEngine(settings.docker_socket)
    manager = RunManager(settings, engine, GitOps(settings))
    token = settings.token.encode()

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        logging.basicConfig(level=logging.INFO)
        await manager.start()
        yield
        await manager.shutdown()

    app = FastAPI(title="Cobble agent-service", lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.manager = manager

    def require_token(authorization: Annotated[str | None, Header()] = None) -> None:
        scheme, _, value = (authorization or "").partition(" ")
        if scheme.lower() != "bearer" or not hmac.compare_digest(value.strip().encode(), token):
            raise RunError(401, "unauthorized")

    auth = Depends(require_token)

    @app.exception_handler(RunError)
    async def _run_error(_request: Request, exc: RunError) -> JSONResponse:
        return _error(exc.status, exc.code, exc.params)

    @app.exception_handler(RequestValidationError)
    async def _invalid(_request: Request, exc: RequestValidationError) -> JSONResponse:
        fields = [".".join(str(p) for p in e["loc"][1:]) for e in exc.errors()]
        return _error(422, "invalid_request", {"fields": fields})

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/v1/runs", status_code=202, response_model=RunCreated, dependencies=[auth])
    async def create_run(body: RunRequest) -> RunCreated:
        return RunCreated(run_id=await manager.create(body))

    @app.get("/v1/runs/{run_id}", response_model=RunStatus, dependencies=[auth])
    async def get_run(run_id: str) -> RunStatus:
        return manager.status(run_id)

    @app.get("/v1/runs/{run_id}/logs", dependencies=[auth])
    async def get_logs(run_id: str, offset: Annotated[int, Query(ge=0)] = 0) -> Response:
        data, next_offset = manager.read_logs(run_id, offset)
        return Response(
            data,
            media_type="text/plain; charset=utf-8",
            headers={"X-Next-Offset": str(next_offset)},
        )

    @app.post("/v1/runs/{run_id}/stop", status_code=204, dependencies=[auth])
    async def stop_run(run_id: str) -> Response:
        await manager.stop(run_id)
        return Response(status_code=204)

    return app
