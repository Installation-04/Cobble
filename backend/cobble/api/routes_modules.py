"""The module store API (ADR 0008). Administrators only; the work is done by the module-manager.

The API never holds the vault key or the Docker socket: it forwards to the module-manager's
internal API and turns its answers into the usual `{"error": {"code", "params"}}` shape.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from redis.exceptions import RedisError

from cobble.events import MODULE_STREAM
from cobble.providers.module_manager import (
    HttpModuleManager,
    ModuleManagerRejected,
    ModuleManagerUnavailable,
)

from .deps import AdminUser, AppSettings, RedisDep
from .errors import ApiError
from .sse import SSE_HEADERS, SseOptions, event_stream, start_id

router = APIRouter()


class OperationBody(BaseModel):
    action: Literal["install", "uninstall"]
    modules: list[str] = Field(min_length=1, max_length=20)
    choices: dict[str, str] = Field(default_factory=dict)
    replace: bool = False
    confirm_cascade: bool = False


def get_manager(request: Request, settings: AppSettings) -> Iterator[HttpModuleManager]:
    injected = getattr(request.app.state, "module_manager", None)  # tests
    if injected is not None:
        yield injected
        return
    client = HttpModuleManager.from_settings(settings)
    try:
        yield client
    finally:
        client.close()


Manager = Annotated[HttpModuleManager, Depends(get_manager)]


def _call[T](action: Callable[[], T]) -> T:
    """Run a manager call, mapping its failures to API errors."""
    try:
        result: T = action()
    except ModuleManagerRejected as exc:
        raise ApiError(exc.status, exc.code, **exc.params) from None
    except ModuleManagerUnavailable:
        raise ApiError(503, "module_manager_unavailable") from None
    return result


@router.get("/modules")
def list_modules(_admin: AdminUser, manager: Manager) -> dict[str, Any]:
    return _call(manager.catalog)


@router.get("/modules/packs")
def list_packs(_admin: AdminUser, manager: Manager) -> dict[str, Any]:
    return _call(manager.packs)


@router.post("/modules/plan")
def plan(body: OperationBody, _admin: AdminUser, manager: Manager) -> dict[str, Any]:
    return _call(lambda: manager.plan(body.model_dump()))


@router.post("/modules/operations", status_code=202)
def start_operation(body: OperationBody, _admin: AdminUser, manager: Manager) -> dict[str, str]:
    operation_id: str = _call(lambda: manager.start_operation(body.model_dump()))
    return {"operation_id": operation_id}


@router.get("/modules/operations/{operation_id}")
def get_operation(operation_id: str, _admin: AdminUser, manager: Manager) -> dict[str, Any]:
    return _call(lambda: manager.operation(operation_id))


@router.get("/modules/stream")
async def stream_events(
    request: Request,
    _admin: AdminUser,
    redis: RedisDep,
    last_event_id: Annotated[str | None, Header()] = None,
    last_event_id_query: Annotated[str | None, Query(alias="last_event_id")] = None,
) -> StreamingResponse:
    try:
        first = start_id(redis, MODULE_STREAM, last_event_id, last_event_id_query)
    except RedisError:
        raise ApiError(503, "queue_unavailable") from None
    options: SseOptions = getattr(request.app.state, "sse", None) or SseOptions()
    return StreamingResponse(
        event_stream(redis, MODULE_STREAM, first, request.is_disconnected, options),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


@router.get("/modules/{module_id}/secrets")
def secret_status(module_id: str, _admin: AdminUser, manager: Manager) -> dict[str, bool]:
    return _call(lambda: manager.secret_status(module_id))
