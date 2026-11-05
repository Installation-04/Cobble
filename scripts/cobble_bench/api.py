"""The part of the Cobble HTTP API the bench uses, and a client for it (standard library only).

`CobbleApi` is the protocol the runner depends on. `HttpCobble` talks to a real instance; the
fake in `fake.py` implements the same protocol in memory so the runner can be tested, and run
with `--dry-run`, without any model, server or money.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from http.cookiejar import CookieJar
from typing import Any, Protocol


class ApiError(Exception):
    """The server answered with an error status (or could not be reached: status 0)."""

    def __init__(self, status: int, body: Any = None) -> None:
        super().__init__(f"HTTP {status}")
        self.status = status
        self.body = body


class CobbleApi(Protocol):
    def login(self, email: str, password: str) -> None: ...
    def model_setup(self) -> dict[str, Any]:
        """`{"effective": {role: [models]}, "default": str | None}` of the instance."""
        ...

    def apply_preset(self, preset_id: str, slots: dict[str, str]) -> None: ...
    def create_project(self, name: str) -> str: ...
    def set_budget(self, project_id: str, budget_usd: str) -> None: ...
    def project(self, project_id: str) -> dict[str, Any]: ...
    def messages(self, project_id: str) -> list[dict[str, Any]]: ...
    def post_message(self, project_id: str, content: str) -> None: ...
    def generate_spec(self, project_id: str, feedback: str | None) -> None: ...
    def spec(self, project_id: str) -> dict[str, Any] | None: ...
    def approve_spec(self, project_id: str) -> None: ...
    def generate_plan(self, project_id: str, feedback: str | None) -> None: ...
    def plan(self, project_id: str) -> dict[str, Any] | None: ...
    def approve_plan(self, project_id: str) -> None: ...
    def start(self, project_id: str) -> None: ...
    def tasks(self, project_id: str) -> list[dict[str, Any]]: ...
    def milestones(self, project_id: str) -> list[dict[str, Any]]: ...
    def validate_milestone(self, project_id: str, ref: str) -> None: ...
    def costs(self, project_id: str) -> dict[str, Any]: ...


class HttpCobble:
    """Session-cookie client of `/api/v1` (the same routes the UI and `e2e_full.sh` use)."""

    def __init__(self, base_url: str, *, timeout_s: float = 60.0) -> None:
        self.base = base_url.rstrip("/") + "/api/v1"
        self.timeout_s = timeout_s
        self._opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))

    def _call(self, method: str, path: str, body: Any = None, *, optional: bool = False) -> Any:
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(  # noqa: S310 - the URL comes from the operator
            self.base + path,
            data=data,
            method=method,
            headers={"Content-Type": "application/json", "X-Requested-With": "cobble"},
        )
        try:
            with self._opener.open(request, timeout=self.timeout_s) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            if optional and exc.code == 404:
                return None
            try:
                detail = json.loads(exc.read() or b"null")
            except ValueError:
                detail = None
            raise ApiError(exc.code, detail) from None
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise ApiError(0, str(exc)) from None
        return json.loads(raw) if raw else None

    def login(self, email: str, password: str) -> None:
        self._call("POST", "/auth/login", {"email": email, "password": password})

    def model_setup(self) -> dict[str, Any]:
        routes = self._call("GET", "/models/routes")
        listing = self._call("GET", "/models")
        return {
            "effective": routes.get("effective", {}),
            "default": listing.get("configured_default"),
            "models": [m.get("name") for m in listing.get("models", [])],
        }

    def apply_preset(self, preset_id: str, slots: dict[str, str]) -> None:
        self._call("POST", f"/models/presets/{preset_id}/apply", slots)

    def create_project(self, name: str) -> str:
        return str(self._call("POST", "/projects", {"name": name})["id"])

    def set_budget(self, project_id: str, budget_usd: str) -> None:
        self._call("PATCH", f"/projects/{project_id}", {"budget_usd": budget_usd})

    def project(self, project_id: str) -> dict[str, Any]:
        for item in self._call("GET", "/projects"):
            if item["id"] == project_id:
                return dict(item)
        raise ApiError(404)

    def messages(self, project_id: str) -> list[dict[str, Any]]:
        return list(self._call("GET", f"/projects/{project_id}/messages"))

    def post_message(self, project_id: str, content: str) -> None:
        self._call("POST", f"/projects/{project_id}/messages", {"content": content})

    def generate_spec(self, project_id: str, feedback: str | None) -> None:
        self._call("POST", f"/projects/{project_id}/spec/generate", {"feedback": feedback})

    def spec(self, project_id: str) -> dict[str, Any] | None:
        return self._call("GET", f"/projects/{project_id}/spec", optional=True)

    def approve_spec(self, project_id: str) -> None:
        self._call("POST", f"/projects/{project_id}/spec/approve")

    def generate_plan(self, project_id: str, feedback: str | None) -> None:
        self._call("POST", f"/projects/{project_id}/plan/generate", {"feedback": feedback})

    def plan(self, project_id: str) -> dict[str, Any] | None:
        return self._call("GET", f"/projects/{project_id}/plan", optional=True)

    def approve_plan(self, project_id: str) -> None:
        self._call("POST", f"/projects/{project_id}/plan/approve")

    def start(self, project_id: str) -> None:
        self._call("POST", f"/projects/{project_id}/start")

    def tasks(self, project_id: str) -> list[dict[str, Any]]:
        return list(self._call("GET", f"/projects/{project_id}/tasks"))

    def milestones(self, project_id: str) -> list[dict[str, Any]]:
        found = self._call("GET", f"/projects/{project_id}/milestones", optional=True)
        return list(found or [])

    def validate_milestone(self, project_id: str, ref: str) -> None:
        self._call("POST", f"/projects/{project_id}/milestones/{ref}/validate")

    def costs(self, project_id: str) -> dict[str, Any]:
        return dict(self._call("GET", f"/projects/{project_id}/costs"))
