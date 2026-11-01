"""HTTP client of the module-manager (ADR 0008): the API's only way to install modules.

Same shape as `HttpAgentRunner`. An unreachable service, a 5xx answer or a rejected token is
`ModuleManagerUnavailable`; a refusal the user can act on (`module_needs_choice`, `module_busy`…)
is `ModuleManagerRejected` and carries the manager's own status, code and params.
"""

from __future__ import annotations

from typing import Any

import httpx

from cobble.config import Settings


class ModuleManagerUnavailable(Exception):
    pass


class ModuleManagerRejected(Exception):
    def __init__(self, status: int, code: str, params: dict[str, Any]) -> None:
        super().__init__(code)
        self.status = status
        self.code = code
        self.params = params


class HttpModuleManager:
    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        timeout_s: float = 20.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            timeout=timeout_s,
            transport=transport,
        )

    @classmethod
    def from_settings(cls, settings: Settings) -> HttpModuleManager:
        return cls(settings.module_manager_url, settings.module_manager_token)

    def close(self) -> None:
        self._client.close()

    def _request(self, method: str, path: str, *, json: dict[str, Any] | None = None) -> Any:
        try:
            response = self._client.request(method, path, json=json)
        except httpx.HTTPError as exc:
            # The message must not echo headers: only the exception type is kept.
            raise ModuleManagerUnavailable(type(exc).__name__) from None
        if response.status_code >= 500 or response.status_code in (401, 403):
            raise ModuleManagerUnavailable(f"HTTP {response.status_code}")
        if response.status_code >= 400:
            try:
                error = response.json()["error"]
                raise ModuleManagerRejected(
                    response.status_code, str(error["code"]), dict(error.get("params") or {})
                )
            except (ValueError, KeyError, TypeError):
                raise ModuleManagerUnavailable("unreadable error") from None
        try:
            return response.json()
        except ValueError:
            raise ModuleManagerUnavailable("unreadable answer") from None

    def catalog(self) -> dict[str, Any]:
        result: dict[str, Any] = self._request("GET", "/v1/catalog")
        return result

    def plan(self, body: dict[str, Any]) -> dict[str, Any]:
        result: dict[str, Any] = self._request("POST", "/v1/plan", json=body)
        return result

    def start_operation(self, body: dict[str, Any]) -> str:
        return str(self._request("POST", "/v1/operations", json=body)["operation_id"])

    def operation(self, operation_id: str) -> dict[str, Any]:
        result: dict[str, Any] = self._request("GET", f"/v1/operations/{operation_id}")
        return result

    def secret_status(self, module_id: str) -> dict[str, bool]:
        result: dict[str, bool] = self._request("GET", f"/v1/modules/{module_id}/secrets")
        return result
