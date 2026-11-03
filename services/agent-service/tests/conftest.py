"""Fixtures: a fake Docker engine and real git repositories in a temp directory."""

from __future__ import annotations

import asyncio
import subprocess
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from cobble_agent_service.config import Settings
from cobble_agent_service.engine import LABEL_RUN, ContainerInfo
from cobble_agent_service.gitops import GitOps
from cobble_agent_service.models import RunRequest
from cobble_agent_service.runs import RunManager

TOKEN = "service-token-for-tests"
FORGEJO_SECRET = "forgejo-secret-token-123"
RUN_TOKEN = "run-token-abcdef"


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


@dataclass
class Ctx:
    """What a fake container script sees."""

    work: Path
    spec: dict[str, Any]
    emit: Callable[[str], None]

    def commit(self, name: str = "agent.txt", text: str = "hello\n") -> None:
        (self.work / name).write_text(text, "utf-8")
        sh("add", name, cwd=self.work)
        sh(
            "-c",
            "user.name=a",
            "-c",
            "user.email=a@b",
            "commit",
            "-qm",
            f"feat: {name}",
            cwd=self.work,
        )


Script = Callable[[Ctx], Awaitable[int]]


async def succeed(ctx: Ctx) -> int:
    ctx.emit("working\n")
    ctx.commit()
    return 0


@dataclass
class FakeContainer:
    id: str
    spec: dict[str, Any]
    status: str = "created"
    exit_code: int | None = None
    queue: asyncio.Queue[bytes | None] = field(default_factory=asyncio.Queue)
    history: bytearray = field(default_factory=bytearray)
    task: asyncio.Task[None] | None = None
    finished: asyncio.Event = field(default_factory=asyncio.Event)


class FakeEngine:
    """In-memory ContainerEngine. `script` plays the role of the container's process."""

    def __init__(self, script: Script = succeed, internal: bool = True) -> None:
        self.script = script
        self.internal = internal
        self.containers: dict[str, FakeContainer] = {}
        self.removed: list[str] = []
        self.killed: list[str] = []
        self.created = 0

    async def network_is_internal(self, name: str) -> bool:
        return self.internal

    async def create(self, name: str, body: dict[str, Any]) -> str:
        self.created += 1
        cid = f"c{self.created:04d}"
        self.containers[cid] = FakeContainer(cid, body)
        return cid

    def _work(self, c: FakeContainer) -> Path:
        mount = c.spec["HostConfig"]["Mounts"][0]
        return Path(mount["Source"])

    async def start(self, container_id: str) -> None:
        c = self.containers[container_id]
        c.status = "running"

        def emit(text: str) -> None:
            data = text.encode()
            c.history.extend(data)
            c.queue.put_nowait(data)

        async def play() -> None:
            try:
                c.exit_code = await self.script(Ctx(self._work(c), c.spec, emit))
            except asyncio.CancelledError:
                c.exit_code = 137
            c.status = "exited"
            c.queue.put_nowait(None)
            c.finished.set()

        c.task = asyncio.create_task(play())

    async def wait(self, container_id: str) -> int:
        c = self.containers[container_id]
        await c.finished.wait()
        assert c.exit_code is not None
        return c.exit_code

    async def kill(self, container_id: str) -> None:
        self.killed.append(container_id)
        c = self.containers.get(container_id)
        if c and c.task and c.status == "running":
            c.task.cancel()

    async def remove(self, container_id: str) -> None:
        self.removed.append(container_id)
        self.containers.pop(container_id, None)

    async def inspect(self, container_id: str) -> ContainerInfo | None:
        c = self.containers.get(container_id)
        if c is None:
            return None
        return ContainerInfo(c.id, c.status, c.exit_code, c.spec["Labels"][LABEL_RUN])

    async def logs(self, container_id: str) -> AsyncIterator[bytes]:
        c = self.containers[container_id]
        # Replay what was emitted before we attached, then follow the live queue.
        replayed = len(c.history)
        if c.history:
            yield bytes(c.history)
        while True:
            item = await c.queue.get()
            if item is None:
                return
            if replayed:
                replayed = max(0, replayed - len(item))
                continue
            yield item

    async def list_agent_containers(self) -> list[ContainerInfo]:
        return [
            ContainerInfo(c.id, c.status, c.exit_code, c.spec["Labels"][LABEL_RUN])
            for c in self.containers.values()
        ]

    async def close(self) -> None:
        return None


@pytest.fixture
def remote(tmp_path: Path) -> Path:
    """A bare 'forge' with repository proj.git (branch main with one commit)."""
    base = tmp_path / "remote"
    bare = base / "proj.git"
    bare.parent.mkdir()
    sh("init", "-q", "--bare", "-b", "main", str(bare))
    seed = tmp_path / "seed"
    sh("init", "-q", "-b", "main", str(seed))
    (seed / "hello.txt").write_text("hello\n", "utf-8")
    sh("add", ".", cwd=seed)
    sh("-c", "user.name=a", "-c", "user.email=a@b", "commit", "-qm", "init", cwd=seed)
    sh("push", "-q", str(bare), "main", cwd=seed)
    return base


@pytest.fixture
def settings(tmp_path: Path, remote: Path) -> Settings:
    data = tmp_path / "data"
    data.mkdir()
    return Settings(
        token=TOKEN,
        data_dir=data,
        data_host_dir=str(data),
        runner_image="cobble-aider-runner:test",
        api_url="http://api:8000/internal/llm/v1",
        forgejo_url=f"file://{remote}",
        forgejo_token=FORGEJO_SECRET,
        loop_threshold=4,
    )


def make_request(settings: Settings, **over: Any) -> RunRequest:
    body: dict[str, Any] = {
        "task_id": "T-001",
        "project_id": "p1",
        "repo_clone_url": f"{settings.forgejo_url}/proj.git",
        "base_branch": "main",
        "branch": "agent/t-001",
        "role": "worker",
        "model": "worker",
        "instructions": "Do the thing.",
        "files": ["hello.txt"],
        "test_command": "pytest -q",
        "limits": {"max_iterations": 5, "max_seconds": 30, "cpu": 1, "memory_mb": 512, "pids": 128},
        "run_token": RUN_TOKEN,
        "marker": "[cobble-task:T-001:worker:1]",
    }
    body.update(over)
    return RunRequest.model_validate(body)


def new_manager(settings: Settings, engine: FakeEngine) -> RunManager:
    return RunManager(settings, engine, GitOps(settings))


async def finished(manager: RunManager, run_id: str, limit: float = 20) -> None:
    deadline = time.monotonic() + limit
    while manager.records[run_id].state == "running":
        if time.monotonic() > deadline:
            raise TimeoutError(f"run {run_id} still running")
        await asyncio.sleep(0.02)
