"""Error format: {"error": {"code": "<snake_case>", "params": {...}}}."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class ApiError(Exception):
    def __init__(self, status: int, code: str, **params: Any) -> None:
        super().__init__(code)
        self.status = status
        self.code = code
        self.params = params


def error_response(status: int, code: str, params: dict[str, Any] | None = None) -> JSONResponse:
    return JSONResponse(
        status_code=status, content={"error": {"code": code, "params": params or {}}}
    )


def _api_error(_request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, ApiError):
        raise exc
    return error_response(exc.status, exc.code, exc.params)


def _validation_error(_request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, RequestValidationError):
        raise exc
    fields: list[str] = []
    for item in exc.errors():
        loc = [str(part) for part in item["loc"]]
        name = loc[1] if len(loc) > 1 else (loc[0] if loc else "")
        if name and name not in fields:
            fields.append(name)
    return error_response(422, "validation_error", {"fields": fields})


_HTTP_CODES = {404: "not_found", 405: "method_not_allowed"}


def _http_error(_request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, StarletteHTTPException):
        raise exc
    code = _HTTP_CODES.get(exc.status_code, "http_error")
    response = error_response(exc.status_code, code)
    if exc.headers:
        response.headers.update(exc.headers)
    return response


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ApiError, _api_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(StarletteHTTPException, _http_error)
