"""FastAPI application: the preview API (`/v1/previews`, bearer token) and the demo proxy
(`/demo/<project_id>/<milestone>/...`, public: the project id is the secret). ADR 0007."""

from __future__ import annotations

import asyncio
import hmac
import logging
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Any

import httpx
from fastapi import Depends, FastAPI, Header, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from starlette.background import BackgroundTask

from .config import Settings
from .engine import ContainerEngine, DockerEngine
from .gitops import Source
from .manager import (
    BUILDING,
    FAILED,
    STOPPED,
    PreviewError,
    PreviewManager,
    ReadyCheck,
    http_ready,
    public_path,
)
from .models import PreviewOut, PreviewRequest, valid_milestone

log = logging.getLogger(__name__)

# Request headers never forwarded to a demo: it must not see Cobble's session or credentials.
DROP_REQUEST = frozenset(
    {
        "host",
        "cookie",
        "authorization",
        "proxy-authorization",
        "x-requested-with",
        "connection",
        "keep-alive",
        "transfer-encoding",
        "te",
        "trailer",
        "upgrade",
        "content-length",
    }
)
DROP_RESPONSE = frozenset(
    {
        "set-cookie",
        "connection",
        "keep-alive",
        "transfer-encoding",
        "te",
        "trailer",
        "upgrade",
        "content-security-policy",
        "access-control-allow-origin",
        "access-control-allow-credentials",
    }
)
SANDBOX_CSP = "sandbox allow-scripts allow-forms allow-popups allow-modals allow-downloads"
METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]
WAKE_TIMEOUT_S = 60.0


def _error(status: int, code: str, params: dict[str, Any] | None = None) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "params": params or {}}}, status_code=status)


def _page(status: int, title: str, message: str, *, refresh: bool = False) -> HTMLResponse:
    meta = '<meta http-equiv="refresh" content="4">' if refresh else ""
    body = (
        f'<!doctype html><html lang="en"><head><meta charset="utf-8">{meta}'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f'<title>{title}</title></head><body style="font-family:system-ui,sans-serif;'
        f'max-width:36rem;margin:3rem auto;padding:0 1rem"><h1>{title}</h1><p>{message}</p>'
        "</body></html>"
    )
    headers = {"Retry-After": "4", "Cache-Control": "no-store"} if refresh else {}
    return HTMLResponse(body, status_code=status, headers=headers)


def create_app(
    settings: Settings | None = None,
    engine: ContainerEngine | None = None,
    *,
    ready: ReadyCheck = http_ready,
    proxy_transport: httpx.AsyncBaseTransport | None = None,
) -> FastAPI:
    settings = settings or Settings.from_env()
    engine = engine or DockerEngine(settings.docker_socket, settings.build_timeout_s)
    manager = PreviewManager(settings, engine, Source(settings), ready=ready)
    token = settings.token.encode()
    client = httpx.AsyncClient(
        transport=proxy_transport,
        timeout=httpx.Timeout(10.0, read=300.0),
        follow_redirects=False,
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        logging.basicConfig(level=logging.INFO)
        await manager.start()
        yield
        await manager.shutdown()
        await client.aclose()

    app = FastAPI(title="Cobble preview-service", lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.manager = manager

    def require_token(authorization: Annotated[str | None, Header()] = None) -> None:
        scheme, _, value = (authorization or "").partition(" ")
        if scheme.lower() != "bearer" or not hmac.compare_digest(value.strip().encode(), token):
            raise PreviewError(401, "unauthorized")

    auth = Depends(require_token)

    @app.exception_handler(PreviewError)
    async def _preview_error(_request: Request, exc: PreviewError) -> JSONResponse:
        return _error(exc.status, exc.code)

    @app.exception_handler(RequestValidationError)
    async def _validation(_request: Request, exc: RequestValidationError) -> JSONResponse:
        fields = sorted({str(e["loc"][-1]) for e in exc.errors() if e["loc"]})
        return _error(422, "validation_error", {"fields": fields})

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    # --- management API ---------------------------------------------------------------

    @app.post("/v1/previews", status_code=202, response_model=PreviewOut, dependencies=[auth])
    async def deploy(body: PreviewRequest) -> PreviewOut:
        record = await manager.deploy(body)
        return manager.view(record)

    @app.get("/v1/previews/{preview_id}", response_model=PreviewOut, dependencies=[auth])
    async def get_preview(preview_id: str) -> PreviewOut:
        record = manager.get(preview_id)
        if record is None:
            raise PreviewError(404, "not_found")
        return manager.view(record)

    @app.delete("/v1/previews/{preview_id}", status_code=204, dependencies=[auth])
    async def delete_preview(preview_id: str) -> Response:
        await manager.remove(preview_id)
        return Response(status_code=204)

    # --- demo proxy -------------------------------------------------------------------

    def _security_headers(headers: dict[str, str]) -> dict[str, str]:
        if settings.sandbox:
            headers["Content-Security-Policy"] = SANDBOX_CSP
            headers["Access-Control-Allow-Origin"] = "*"
        headers["Referrer-Policy"] = "no-referrer"
        headers["X-Content-Type-Options"] = "nosniff"
        return headers

    @app.api_route("/demo/{project_id}/{milestone}", methods=["GET", "HEAD"])
    async def slash(project_id: str, milestone: str, request: Request) -> Response:
        # Relative asset paths need the trailing slash.
        query = f"?{request.url.query}" if request.url.query else ""
        return RedirectResponse(f"{public_path(project_id, milestone)}{query}", status_code=308)

    @app.api_route("/demo/{project_id}/{milestone}/{path:path}", methods=METHODS)
    async def proxy(project_id: str, milestone: str, path: str, request: Request) -> Response:
        try:
            uuid.UUID(project_id)
        except ValueError:
            return _page(404, "Not found", "This demo does not exist.")
        if not valid_milestone(milestone):
            return _page(404, "Not found", "This demo does not exist.")
        if settings.sandbox and request.method == "OPTIONS":
            return Response(
                status_code=204,
                headers={
                    "Access-Control-Allow-Origin": "*",
                    "Access-Control-Allow-Methods": ", ".join(METHODS),
                    "Access-Control-Allow-Headers": request.headers.get(
                        "access-control-request-headers", "*"
                    ),
                    "Access-Control-Max-Age": "600",
                },
            )
        record = manager.get(f"{project_id}-{milestone}")
        if record is None:
            return _page(404, "Not found", "This demo does not exist.")
        if record.state == BUILDING:
            return _page(
                503,
                "Building the demo",
                "The demo is being built. This page reloads itself.",
                refresh=True,
            )
        if record.state == FAILED:
            return _page(
                502, "The demo could not be built", "Ask Cobble to rebuild this milestone."
            )
        manager.touch(record)
        if record.state == STOPPED:
            try:
                await asyncio.wait_for(manager.wake(record), WAKE_TIMEOUT_S)
            except TimeoutError:
                return _page(503, "Starting the demo", "The demo is starting.", refresh=True)
            if record.state != "running":
                return _page(503, "Starting the demo", "The demo is starting.", refresh=True)
        prefix = public_path(project_id, milestone).rstrip("/")
        url = f"{manager.upstream(record)}/{path}"
        if request.url.query:
            url += f"?{request.url.query}"
        headers = {k: v for k, v in request.headers.items() if k.lower() not in DROP_REQUEST}
        headers["X-Forwarded-Prefix"] = prefix
        headers["X-Forwarded-Proto"] = request.headers.get("x-forwarded-proto", request.url.scheme)
        has_body = request.method in {"POST", "PUT", "PATCH", "DELETE"}
        upstream_request = client.build_request(
            request.method, url, headers=headers, content=request.stream() if has_body else None
        )
        try:
            upstream = await client.send(upstream_request, stream=True)
        except httpx.HTTPError:
            return _page(502, "The demo does not answer", "It may be starting. Try again shortly.")
        out = {k: v for k, v in upstream.headers.items() if k.lower() not in DROP_RESPONSE}
        location = out.get("location")
        if location and location.startswith("/") and not location.startswith("//"):
            out["location"] = prefix + location
        return StreamingResponse(
            upstream.aiter_raw(),
            status_code=upstream.status_code,
            headers=_security_headers(out),
            background=BackgroundTask(upstream.aclose),
        )

    return app
