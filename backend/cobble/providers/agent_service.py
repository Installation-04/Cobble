"""AgentRunner backed by the pack's agent-service (ADR 0006).

The agent-service is the only component that touches Docker. This module is its HTTP client:
`start` -> POST /v1/runs, `poll` -> GET /v1/runs/{id}, `stop` -> POST /v1/runs/{id}/stop.
An unreachable service or a 5xx answer is `AgentUnavailable` (the scheduler retries later and
does not count it as a failed attempt); an unknown run is `AgentRunNotFound`.

It also holds `build_pack_services`, the one place that builds the fixed pack's collaborators
from the settings (this package is where product names are allowed).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from cobble.capabilities.agent import (
    AgentOutcome,
    AgentRejected,
    AgentResult,
    AgentRunNotFound,
    AgentTask,
    AgentUnavailable,
    run_blocking,
)
from cobble.capabilities.ci import CIProvider
from cobble.capabilities.git import GitProvider
from cobble.capabilities.preview import PreviewProvider
from cobble.config import Settings

log = logging.getLogger(__name__)

_STATES = {
    "done": AgentOutcome.DONE,
    "failed": AgentOutcome.FAILED,
    "timeout": AgentOutcome.TIMEOUT,
    "loop_detected": AgentOutcome.LOOP_DETECTED,
    "stopped": AgentOutcome.STOPPED,
}


class HttpAgentRunner:
    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        timeout_s: float = 15.0,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._sleep = sleep
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            timeout=timeout_s,
            transport=transport,
        )

    @classmethod
    def from_settings(cls, settings: Settings) -> HttpAgentRunner:
        return cls(settings.agent_service_url, settings.agent_service_token)

    def close(self) -> None:
        self._client.close()

    def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        try:
            return self._client.request(method, path, json=json, params=params, headers=headers)
        except httpx.HTTPError as exc:
            # The message must not echo headers: only the exception type is kept.
            raise AgentUnavailable(f"agent service unreachable: {type(exc).__name__}") from None

    # --- AgentRunner ----------------------------------------------------------------------

    def start(self, task: AgentTask) -> str:
        body: dict[str, Any] = {
            "task_id": str(task.task_id),
            "project_id": str(task.project_id),
            "repo_clone_url": task.repo_clone_url,
            "base_branch": task.base_branch,
            "branch": task.branch,
            "role": task.role.value,
            "model": task.model,
            "instructions": task.instructions,
            "files": list(task.files),
            "test_command": task.test_command,
            "limits": {
                "max_iterations": task.limits.max_iterations,
                "max_seconds": task.limits.max_seconds,
                "cpu": task.limits.cpu,
                "memory_mb": task.limits.memory_mb,
                "pids": task.limits.pids,
            },
            "run_token": task.run_token,
            "marker": task.marker,
        }
        response = self._request("POST", "/v1/runs", json=body)
        if response.status_code in (200, 201, 202):
            try:
                return str(response.json()["run_id"])
            except (ValueError, KeyError, TypeError):
                raise AgentUnavailable("agent service sent an unreadable answer") from None
        if response.status_code in (400, 401, 403, 409, 422):
            raise AgentRejected(f"agent service refused the run (HTTP {response.status_code})")
        raise AgentUnavailable(f"agent service answered HTTP {response.status_code}")

    def poll(self, run_id: str) -> AgentResult | None:
        response = self._request("GET", f"/v1/runs/{run_id}")
        if response.status_code == 404:
            raise AgentRunNotFound(run_id)
        if response.status_code != 200:
            raise AgentUnavailable(f"agent service answered HTTP {response.status_code}")
        try:
            data = response.json()
            state = str(data["state"])
        except (ValueError, KeyError, TypeError):
            raise AgentUnavailable("agent service sent an unreadable answer") from None
        if state == "running":
            return None
        outcome = _STATES.get(state)
        log_tail = str(data.get("log_tail") or "")
        if outcome is None:
            outcome = AgentOutcome.FAILED
            log_tail = f"unknown run state {state!r}\n{log_tail}".rstrip()
        exit_code = data.get("exit_code")
        return AgentResult(
            outcome,
            iterations=int(data.get("iterations") or 0),
            log=log_tail,
            head_sha=str(data["head_sha"]) if data.get("head_sha") else None,
            exit_code=int(exit_code) if isinstance(exit_code, int) else None,
        )

    def stop(self, run_id: str) -> None:
        response = self._request("POST", f"/v1/runs/{run_id}/stop")
        if response.status_code in (200, 202, 204, 404):  # 404: already gone
            return
        raise AgentUnavailable(f"agent service answered HTTP {response.status_code}")

    def logs(self, run_id: str, offset: int = 0) -> tuple[str, int]:
        response = self._request(
            "GET",
            f"/v1/runs/{run_id}/logs",
            params={"offset": max(offset, 0)},
            headers={"Accept": "text/plain"},
        )
        if response.status_code == 404:
            raise AgentRunNotFound(run_id)
        if response.status_code != 200:
            raise AgentUnavailable(f"agent service answered HTTP {response.status_code}")
        text = response.text
        try:
            next_offset = int(response.headers["X-Next-Offset"])
        except (KeyError, ValueError):
            next_offset = max(offset, 0) + len(response.content)
        return text, next_offset

    def run(self, task: AgentTask) -> AgentResult:
        return run_blocking(self, task, timeout_s=task.limits.max_seconds + 60.0, sleep=self._sleep)


@dataclass(frozen=True)
class PackServices:
    git: GitProvider
    ci: CIProvider
    agents: HttpAgentRunner
    # None: no preview service configured, the demo flow is off (the project is `done` when
    # every task is merged).
    preview: PreviewProvider | None = None


def build_pack_services(settings: Settings, env_file: Path | None = None) -> PackServices | None:
    """The fixed pack's git, CI and agent runner, or None when it is not configured.

    The pack's own settings come from COBBLE_PACK_* (optionally completed by `env_file`).
    """
    from .forgejo import ForgejoGit
    from .settings import load_settings
    from .woodpecker import WoodpeckerCI

    pack = load_settings(env_file)
    if not pack.configured():
        log.warning("the pack is not configured (COBBLE_PACK_* tokens are empty)")
        return None
    runtime = build_runtime_services(settings)
    if runtime is None:
        return None
    agents, preview = runtime
    ci = WoodpeckerCI(pack)
    return PackServices(ForgejoGit(pack, ci=ci), ci, agents, preview)


def build_runtime_services(
    settings: Settings,
) -> tuple[HttpAgentRunner, PreviewProvider | None] | None:
    """The agent runner and the optional preview service, or None without an agent token."""
    if not settings.agent_service_token:
        log.warning("COBBLE_AGENT_SERVICE_TOKEN is empty")
        return None
    preview: PreviewProvider | None = None
    if settings.preview_service_token:
        from .preview_service import HttpPreviewProvider

        preview = HttpPreviewProvider.from_settings(settings)
    else:
        log.warning("COBBLE_PREVIEW_SERVICE_TOKEN is empty: milestone demos are disabled")
    return HttpAgentRunner.from_settings(settings), preview
