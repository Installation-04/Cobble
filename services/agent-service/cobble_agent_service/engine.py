"""Minimal Docker Engine API client over the unix socket (httpx, no Docker SDK).

Only what agent-service needs: inspect a network, create/start/wait/kill/remove a container,
follow its logs, and find containers by label. `ContainerEngine` is the seam the tests fake.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

API_VERSION = "v1.45"  # volume subpath mounts need >= 1.45 (Docker 26)
LABEL = "cobble.agent"
LABEL_RUN = "cobble.run_id"


class EngineError(RuntimeError):
    """The Docker daemon refused or failed a request."""


@dataclass(frozen=True)
class ContainerInfo:
    id: str
    status: str  # created | running | exited | ...
    exit_code: int | None
    run_id: str


class ContainerEngine(Protocol):
    async def network_is_internal(self, name: str) -> bool: ...
    async def create(self, name: str, body: dict[str, Any]) -> str: ...
    async def start(self, container_id: str) -> None: ...
    async def wait(self, container_id: str) -> int: ...
    async def kill(self, container_id: str) -> None: ...
    async def remove(self, container_id: str) -> None: ...
    async def inspect(self, container_id: str) -> ContainerInfo | None: ...
    def logs(self, container_id: str) -> AsyncIterator[bytes]: ...
    async def list_agent_containers(self) -> list[ContainerInfo]: ...
    async def close(self) -> None: ...


def _info(data: dict[str, Any]) -> ContainerInfo:
    state = data.get("State", {})
    labels = data.get("Config", {}).get("Labels", {}) or {}
    status = str(state.get("Status", "unknown"))
    return ContainerInfo(
        id=str(data["Id"]),
        status=status,
        exit_code=int(state["ExitCode"]) if status == "exited" else None,
        run_id=str(labels.get(LABEL_RUN, "")),
    )


class DockerEngine:
    def __init__(self, socket_path: str) -> None:
        self._client = httpx.AsyncClient(
            transport=httpx.AsyncHTTPTransport(uds=socket_path),
            base_url=f"http://docker/{API_VERSION}",
            timeout=httpx.Timeout(30.0, read=None),
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def _request(
        self, method: str, path: str, ok: tuple[int, ...] = (200, 201, 204), **kw: Any
    ) -> httpx.Response:
        try:
            response = await self._client.request(method, path, **kw)
        except httpx.HTTPError as exc:
            raise EngineError(f"docker daemon unreachable: {exc}") from exc
        if response.status_code not in ok:
            raise EngineError(
                f"docker {method} {path}: {response.status_code} {response.text[:300]}"
            )
        return response

    async def network_is_internal(self, name: str) -> bool:
        data = (await self._request("GET", f"/networks/{name}")).json()
        return bool(data.get("Internal"))

    async def create(self, name: str, body: dict[str, Any]) -> str:
        response = await self._request(
            "POST", "/containers/create", params={"name": name}, json=body
        )
        return str(response.json()["Id"])

    async def start(self, container_id: str) -> None:
        await self._request("POST", f"/containers/{container_id}/start", ok=(204, 304))

    async def wait(self, container_id: str) -> int:
        response = await self._request("POST", f"/containers/{container_id}/wait")
        return int(response.json()["StatusCode"])

    async def kill(self, container_id: str) -> None:
        # 409: not running (already exited); 404: gone. Both mean there is nothing to kill.
        await self._request("POST", f"/containers/{container_id}/kill", ok=(204, 404, 409))

    async def remove(self, container_id: str) -> None:
        await self._request(
            "DELETE", f"/containers/{container_id}", ok=(204, 404), params={"force": 1}
        )

    async def inspect(self, container_id: str) -> ContainerInfo | None:
        response = await self._request("GET", f"/containers/{container_id}/json", ok=(200, 404))
        return None if response.status_code == 404 else _info(response.json())

    async def logs(self, container_id: str) -> AsyncIterator[bytes]:
        params = {"follow": "1", "stdout": "1", "stderr": "1"}
        async with self._client.stream(
            "GET", f"/containers/{container_id}/logs", params=params
        ) as response:
            if response.status_code != 200:
                raise EngineError(f"docker logs: {response.status_code}")
            # Containers run with a TTY, so the stream is raw (not multiplexed).
            async for chunk in response.aiter_raw():
                yield chunk

    async def list_agent_containers(self) -> list[ContainerInfo]:

        filters = json.dumps({"label": [f"{LABEL}=1"]})
        response = await self._request(
            "GET", "/containers/json", params={"all": 1, "filters": filters}
        )
        out: list[ContainerInfo] = []
        for item in response.json():
            labels = item.get("Labels", {}) or {}
            state = str(item.get("State", "unknown"))
            out.append(
                ContainerInfo(
                    id=str(item["Id"]),
                    status=state,
                    exit_code=None,
                    run_id=str(labels.get(LABEL_RUN, "")),
                )
            )
        return out
