"""Minimal Docker Engine API client over the unix socket (httpx, no Docker SDK).

Only what preview-service needs: build an image from a tar context, create/start/stop/remove
a container, inspect it, list the previews' containers. `ContainerEngine` is the seam the
tests fake.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import httpx

API_VERSION = "v1.45"
LABEL = "cobble.preview"
LABEL_ID = "cobble.preview.id"


class EngineError(RuntimeError):
    """The Docker daemon refused or failed a request. `str()` never holds credentials."""


@dataclass(frozen=True)
class ContainerInfo:
    id: str
    running: bool
    preview_id: str


class ContainerEngine(Protocol):
    async def build(
        self, tag: str, context: Path, labels: Mapping[str, str], build_args: Mapping[str, str]
    ) -> None: ...
    async def create(self, name: str, body: dict[str, Any]) -> str: ...
    async def start(self, container_id: str) -> None: ...
    async def stop(self, container_id: str) -> None: ...
    async def remove(self, container_id: str) -> None: ...
    async def inspect(self, container_id: str) -> ContainerInfo | None: ...
    async def list_previews(self) -> list[ContainerInfo]: ...
    async def remove_image(self, tag: str) -> None: ...
    async def image_exists(self, tag: str) -> bool: ...
    async def close(self) -> None: ...


async def _file_chunks(path: Path) -> AsyncIterator[bytes]:
    with path.open("rb") as fh:
        while chunk := fh.read(1 << 20):
            yield chunk


class DockerEngine:
    def __init__(self, socket_path: str, build_timeout_s: float = 900.0) -> None:
        self._build_timeout = build_timeout_s
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
            raise EngineError(f"docker daemon unreachable: {type(exc).__name__}") from None
        if response.status_code not in ok:
            raise EngineError(
                f"docker {method} {path}: {response.status_code} {response.text[:300]}"
            )
        return response

    async def build(
        self, tag: str, context: Path, labels: Mapping[str, str], build_args: Mapping[str, str]
    ) -> None:
        params = {
            "t": tag,
            "rm": "1",
            "forcerm": "1",
            "pull": "0",
            "dockerfile": "Dockerfile",
            "labels": json.dumps(dict(labels)),
            "buildargs": json.dumps(dict(build_args)),
        }
        last_error = ""
        tail: list[str] = []
        try:
            async with self._client.stream(
                "POST",
                "/build",
                params=params,
                content=_file_chunks(context),
                headers={"Content-Type": "application/x-tar"},
                timeout=httpx.Timeout(30.0, read=self._build_timeout),
            ) as response:
                if response.status_code != 200:
                    body = (await response.aread()).decode("utf-8", "replace")[:300]
                    raise EngineError(f"docker build: {response.status_code} {body}")
                async for line in response.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        item = json.loads(line)
                    except ValueError:
                        continue
                    if item.get("error"):
                        last_error = str(item["error"])
                    elif item.get("stream", "").strip():
                        tail.append(str(item["stream"]).rstrip())
                        del tail[:-15]
        except httpx.HTTPError as exc:
            raise EngineError(f"docker build failed: {type(exc).__name__}") from None
        if last_error:
            raise EngineError(("\n".join(tail) + "\n" + last_error).strip()[-1500:])

    async def create(self, name: str, body: dict[str, Any]) -> str:
        response = await self._request(
            "POST", "/containers/create", params={"name": name}, json=body
        )
        return str(response.json()["Id"])

    async def start(self, container_id: str) -> None:
        await self._request("POST", f"/containers/{container_id}/start", ok=(204, 304))

    async def stop(self, container_id: str) -> None:
        await self._request(
            "POST", f"/containers/{container_id}/stop", ok=(204, 304, 404), params={"t": 5}
        )

    async def remove(self, container_id: str) -> None:
        await self._request(
            "DELETE", f"/containers/{container_id}", ok=(204, 404), params={"force": 1}
        )

    async def inspect(self, container_id: str) -> ContainerInfo | None:
        response = await self._request("GET", f"/containers/{container_id}/json", ok=(200, 404))
        if response.status_code == 404:
            return None
        data = response.json()
        labels = data.get("Config", {}).get("Labels", {}) or {}
        return ContainerInfo(
            str(data["Id"]),
            bool(data.get("State", {}).get("Running")),
            str(labels.get(LABEL_ID, "")),
        )

    async def list_previews(self) -> list[ContainerInfo]:
        filters = json.dumps({"label": [f"{LABEL}=1"]})
        response = await self._request(
            "GET", "/containers/json", params={"all": 1, "filters": filters}
        )
        return [
            ContainerInfo(
                str(item["Id"]),
                str(item.get("State")) == "running",
                str((item.get("Labels") or {}).get(LABEL_ID, "")),
            )
            for item in response.json()
        ]

    async def remove_image(self, tag: str) -> None:
        await self._request("DELETE", f"/images/{tag}", ok=(200, 404, 409))

    async def image_exists(self, tag: str) -> bool:
        response = await self._request("GET", f"/images/{tag}/json", ok=(200, 404))
        return response.status_code == 200
