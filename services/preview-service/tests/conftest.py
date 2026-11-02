"""Fixtures: a fake Docker engine, a real local git remote and an in-memory upstream."""

from __future__ import annotations

import subprocess
import tarfile
from collections.abc import AsyncIterator, Mapping
from pathlib import Path
from typing import Any

import httpx
import pytest

from cobble_preview_service.app import create_app
from cobble_preview_service.config import Settings
from cobble_preview_service.engine import LABEL_ID, ContainerInfo, EngineError

TOKEN = "preview-service-token-for-tests"
FORGEJO_SECRET = "forgejo-secret-token-123"
PID = "11111111-1111-1111-1111-111111111111"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def sh(*args: str, cwd: Path | None = None) -> str:
    out = subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        env={
            "PATH": "/usr/bin:/bin:/usr/local/bin",
            "HOME": "/nonexistent",
            "GIT_CONFIG_GLOBAL": "/dev/null",
        },
    )
    return out.stdout.strip()


class FakeEngine:
    """In-memory ContainerEngine that records what was asked of the daemon."""

    def __init__(self) -> None:
        self.builds: list[dict[str, Any]] = []
        self.images: set[str] = set()
        self.containers: dict[str, dict[str, Any]] = {}
        self.running: set[str] = set()
        self.removed_images: list[str] = []
        self.build_error = ""
        self.exit_at_start = False
        self._n = 0

    async def build(
        self, tag: str, context: Path, labels: Mapping[str, str], build_args: Mapping[str, str]
    ) -> None:
        with tarfile.open(context) as tar:
            names = tar.getnames()
        self.builds.append(
            {"tag": tag, "names": names, "labels": dict(labels), "args": dict(build_args)}
        )
        if self.build_error:
            raise EngineError(self.build_error)
        self.images.add(tag)

    async def create(self, name: str, body: dict[str, Any]) -> str:
        self._n += 1
        cid = f"c{self._n}"
        self.containers[cid] = {"name": name, "body": body}
        return cid

    async def start(self, container_id: str) -> None:
        if not self.exit_at_start:
            self.running.add(container_id)

    async def stop(self, container_id: str) -> None:
        self.running.discard(container_id)

    async def remove(self, container_id: str) -> None:
        for cid, c in list(self.containers.items()):
            if cid == container_id or c["name"] == container_id:
                self.containers.pop(cid)
                self.running.discard(cid)

    async def inspect(self, container_id: str) -> ContainerInfo | None:
        c = self.containers.get(container_id)
        if c is None:
            return None
        return ContainerInfo(
            container_id, container_id in self.running, c["body"]["Labels"][LABEL_ID]
        )

    async def list_previews(self) -> list[ContainerInfo]:
        return [
            ContainerInfo(cid, cid in self.running, c["body"]["Labels"][LABEL_ID])
            for cid, c in self.containers.items()
        ]

    async def remove_image(self, tag: str) -> None:
        self.removed_images.append(tag)
        self.images.discard(tag)

    async def image_exists(self, tag: str) -> bool:
        return tag in self.images

    async def close(self) -> None:
        return None

    @property
    def live(self) -> list[dict[str, Any]]:
        return [c for cid, c in self.containers.items() if cid in self.running]


class Upstream:
    """What the demo container 'answers'; records the requests it got."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.status = 200
        self.body = b"<html>hello demo</html>"
        self.headers: dict[str, str] = {
            "content-type": "text/html",
            "set-cookie": "sid=1",
            "x-demo": "yes",
        }

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        # A streamed body, like a real server's (a response built with `content=` is already read).
        return httpx.Response(self.status, headers=self.headers, stream=httpx.ByteStream(self.body))


@pytest.fixture
def remote(tmp_path: Path) -> Path:
    """A bare forge holding cobble-bot/proj.git: branch main, tag milestone-M1 with a Dockerfile."""
    base = tmp_path / "remote"
    bare = base / "cobble-bot" / "proj.git"
    bare.parent.mkdir(parents=True)
    sh("init", "-q", "--bare", "-b", "main", str(bare))
    seed = tmp_path / "seed"
    sh("init", "-q", "-b", "main", str(seed))
    (seed / "Dockerfile").write_text("FROM scratch\n", "utf-8")
    (seed / "app.txt").write_text("hello\n", "utf-8")
    sh("add", ".", cwd=seed)
    sh("-c", "user.name=a", "-c", "user.email=a@b", "commit", "-qm", "init", cwd=seed)
    sh("tag", "milestone-M1", cwd=seed)
    sh("tag", "milestone-M1-r2", cwd=seed)
    (seed / "NODOCKER").write_text("x", "utf-8")
    sh("rm", "-q", "Dockerfile", cwd=seed)
    sh("add", ".", cwd=seed)
    sh("-c", "user.name=a", "-c", "user.email=a@b", "commit", "-qm", "no dockerfile", cwd=seed)
    sh("tag", "milestone-M2", cwd=seed)
    sh("push", "-q", str(bare), "main", "--tags", cwd=seed)
    return base


@pytest.fixture
def settings(tmp_path: Path, remote: Path) -> Settings:
    data = tmp_path / "data"
    data.mkdir()
    return Settings(
        token=TOKEN,
        forgejo_url=f"file://{remote}",
        forgejo_token=FORGEJO_SECRET,
        data_dir=data,
        idle_ttl_s=100.0,
        reap_interval_s=3600.0,
        max_running=2,
    )


def clone_url(settings: Settings, name: str = "proj") -> str:
    return f"{settings.forgejo_url}/cobble-bot/{name}.git"


def payload(settings: Settings, **over: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "project_id": PID,
        "milestone": "M1",
        "repo_clone_url": clone_url(settings),
        "ref": "milestone-M1",
    }
    body.update(over)
    return body


async def always_ready(_url: str) -> bool:
    return True


class Clock:
    def __init__(self) -> None:
        self.now = 1_000_000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def engine() -> FakeEngine:
    return FakeEngine()


@pytest.fixture
def upstream() -> Upstream:
    return Upstream()


@pytest.fixture
async def client(
    settings: Settings, engine: FakeEngine, upstream: Upstream
) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(
        settings, engine, ready=always_ready, proxy_transport=httpx.MockTransport(upstream)
    )
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t", headers=AUTH) as c:
            c.app = app  # type: ignore[attr-defined]
            yield c
