"""Small httpx wrapper shared by the pack clients: auth header, error mapping."""

from __future__ import annotations

from typing import Any

import httpx

from .errors import (
    ProviderAuthError,
    ProviderConflict,
    ProviderError,
    ProviderNotFound,
    ProviderUnavailable,
)


def _message(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.reason_phrase
    if isinstance(body, dict):
        text = body.get("message") or body.get("error") or body.get("errors")
        if text:
            return str(text)[:300]
    return response.reason_phrase


class Api:
    """JSON client for one service. The token only lives in the Authorization header."""

    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        service: str,
        auth_scheme: str,
        timeout: float,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.service = service
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"{auth_scheme} {token}", "Accept": "application/json"},
            timeout=timeout,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
        ok: tuple[int, ...] = (200, 201, 204),
    ) -> Any:
        try:
            response = self._client.request(method, path, params=params, json=json)
        except httpx.HTTPError as exc:
            # str(exc) may echo the URL, never the headers.
            raise ProviderUnavailable(f"{self.service} unreachable: {type(exc).__name__}") from None
        if response.status_code in ok:
            if response.status_code == 204 or not response.content:
                return None
            try:
                return response.json()
            except ValueError:
                return response.text
        detail = f"{self.service} {method} {path}: HTTP {response.status_code} {_message(response)}"
        status = response.status_code
        if status in (401, 403):
            raise ProviderAuthError(detail, status=status)
        if status == 404:
            raise ProviderNotFound(detail, status=status)
        if status in (409, 422):
            raise ProviderConflict(detail, status=status)
        raise ProviderError(detail, status=status)
