"""HTTP client of the module-manager (ADR 0008): the API's only way to install modules.

Same shape as `HttpAgentRunner`. An unreachable service, a 5xx answer or a rejected token is
`ModuleManagerUnavailable`; a refusal the user can act on (`module_needs_choice`, `module_busy`…)
is `ModuleManagerRejected` and carries the manager's own status, code and params.
"""

from __future__ import annotations

from typing import Any

import httpx

from cobble.config import Settings

# Changing a model connection restarts the language-model gateway and waits until it is healthy
# (about 20 s, up to several minutes on a slow machine): the request must outlast that, or the
# caller would report "unavailable" for a change the manager goes on to complete.
GATEWAY_CHANGE_TIMEOUT_S = 330.0
USE_DEFAULT: Any = httpx.USE_CLIENT_DEFAULT

# Refusals the module-manager reports with a 5xx status (the manager works; what it asked for
# failed): they reach the user as such instead of as "the manager is not available".
SERVER_SIDE_REFUSALS = frozenset({"model_gateway_failed"})


def _refusal_code(response: httpx.Response) -> str | None:
    try:
        return str(response.json()["error"]["code"])
    except (ValueError, KeyError, TypeError):
        return None


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

    def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> Any:
        try:
            response = self._client.request(
                method, path, json=json, timeout=timeout if timeout is not None else USE_DEFAULT
            )
        except httpx.HTTPError as exc:
            # The message must not echo headers: only the exception type is kept.
            raise ModuleManagerUnavailable(type(exc).__name__) from None
        if response.status_code >= 500 and _refusal_code(response) not in SERVER_SIDE_REFUSALS:
            raise ModuleManagerUnavailable(f"HTTP {response.status_code}")
        if response.status_code in (401, 403):
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

    def models(self) -> dict[str, Any]:
        result: dict[str, Any] = self._request("GET", "/v1/models")
        return result

    def put_model(self, name: str, body: dict[str, Any]) -> dict[str, Any]:
        result: dict[str, Any] = self._request(
            "PUT", f"/v1/models/{name}", json=body, timeout=GATEWAY_CHANGE_TIMEOUT_S
        )
        return result

    def delete_model(self, name: str) -> dict[str, Any]:
        result: dict[str, Any] = self._request(
            "DELETE", f"/v1/models/{name}", timeout=GATEWAY_CHANGE_TIMEOUT_S
        )
        return result

    def set_default_model(self, name: str) -> dict[str, Any]:
        result: dict[str, Any] = self._request("POST", f"/v1/models/{name}/default")
        return result

    def packs(self) -> dict[str, Any]:
        result: dict[str, Any] = self._request("GET", "/v1/packs")
        return result

    def plan(self, body: dict[str, Any]) -> dict[str, Any]:
        result: dict[str, Any] = self._request("POST", "/v1/plan", json=body)
        return result

    def start_operation(self, body: dict[str, Any]) -> str:
        return str(self._request("POST", "/v1/operations", json=body)["operation_id"])

    def operation(self, operation_id: str) -> dict[str, Any]:
        result: dict[str, Any] = self._request("GET", f"/v1/operations/{operation_id}")
        return result

    def connections(self) -> dict[str, dict[str, Any]]:
        """Running modules with their in-network URL and core-visible secrets (worker only)."""
        result: dict[str, dict[str, Any]] = self._request("GET", "/v1/connections")["connections"]
        return result

    def secret_status(self, module_id: str) -> dict[str, bool]:
        result: dict[str, bool] = self._request("GET", f"/v1/modules/{module_id}/secrets")
        return result
