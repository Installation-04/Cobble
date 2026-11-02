"""PreviewProvider backed by the pack's preview-service (ADR 0007).

The preview-service is the component that builds and runs the generated apps (it holds the
Docker socket). This module is its HTTP client: `deploy` -> POST /v1/previews, `status` ->
GET /v1/previews/{id}, `remove` -> DELETE /v1/previews/{id}. An unreachable service or a 5xx
answer is `PreviewUnavailable` (the scheduler retries later); a 4xx is `PreviewRejected`.
"""

from __future__ import annotations

import uuid
from typing import Any

import httpx

from cobble.capabilities.preview import (
    PreviewRejected,
    PreviewRequest,
    PreviewState,
    PreviewStatus,
    PreviewUnavailable,
)


def preview_id(project_id: uuid.UUID, milestone: str) -> str:
    return f"{project_id}-{milestone}"


class HttpPreviewProvider:
    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        timeout_s: float = 15.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            timeout=timeout_s,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def _request(
        self, method: str, path: str, *, json: dict[str, Any] | None = None
    ) -> httpx.Response:
        try:
            return self._client.request(method, path, json=json)
        except httpx.HTTPError as exc:
            raise PreviewUnavailable(f"preview service unreachable: {type(exc).__name__}") from None

    @staticmethod
    def _status(response: httpx.Response) -> PreviewStatus:
        try:
            data = response.json()
            state = PreviewState(str(data["state"]))
            return PreviewStatus(state, str(data["path"]), str(data.get("detail") or ""))
        except (ValueError, KeyError, TypeError):
            raise PreviewUnavailable("preview service sent an unreadable answer") from None

    def deploy(self, request: PreviewRequest) -> PreviewStatus:
        response = self._request(
            "POST",
            "/v1/previews",
            json={
                "project_id": str(request.project_id),
                "milestone": request.milestone,
                "repo_clone_url": request.repo_clone_url,
                "ref": request.ref,
            },
        )
        if response.status_code in (200, 201, 202):
            return self._status(response)
        if response.status_code in (400, 401, 403, 409, 422):
            raise PreviewRejected(
                f"preview service refused the request (HTTP {response.status_code})"
            )
        raise PreviewUnavailable(f"preview service answered HTTP {response.status_code}")

    def status(self, project_id: uuid.UUID, milestone: str) -> PreviewStatus | None:
        response = self._request("GET", f"/v1/previews/{preview_id(project_id, milestone)}")
        if response.status_code == 404:
            return None
        if response.status_code != 200:
            raise PreviewUnavailable(f"preview service answered HTTP {response.status_code}")
        return self._status(response)

    def remove(self, project_id: uuid.UUID, milestone: str) -> None:
        response = self._request("DELETE", f"/v1/previews/{preview_id(project_id, milestone)}")
        if response.status_code in (200, 202, 204, 404):
            return
        raise PreviewUnavailable(f"preview service answered HTTP {response.status_code}")
