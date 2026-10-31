"""Preview lifecycle: build the image of a tag, run it, stop it when idle, remember all that.

One preview per (project, milestone); its id is `<project_id>-<milestone>`. States:
`building` (clone, build, start), `running`, `stopped` (idle: the image is kept and the
container is started again on the next request), `failed`. The public API reports `stopped`
as `running` with `idle: true`, since the preview wakes up by itself.

Metadata lives in `<data>/previews.json` (atomic writes), so a restart of the service neither
forgets the previews nor leaves a half-built one behind: unfinished builds are started again.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import re
import shutil
import time
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path

import httpx

from .config import Settings
from .engine import LABEL, LABEL_ID, ContainerEngine, EngineError
from .gitops import Source, SourceError
from .models import PreviewOut, PreviewRequest

log = logging.getLogger(__name__)

BUILDING = "building"
RUNNING = "running"
STOPPED = "stopped"
FAILED = "failed"
NON_ROOT = "10001:10001"

ReadyCheck = Callable[[str], Awaitable[bool]]


@dataclass
class Record:
    id: str
    project_id: str
    milestone: str
    ref: str
    repo_clone_url: str
    state: str = BUILDING
    detail: str = ""
    image: str = ""
    last_access: float = field(default_factory=time.time)


class PreviewError(Exception):
    def __init__(self, status: int, code: str) -> None:
        super().__init__(code)
        self.status = status
        self.code = code


def public_path(project_id: str, milestone: str) -> str:
    return f"/demo/{project_id}/{milestone}/"


def container_name(preview_id: str) -> str:
    return f"cobble-preview-{preview_id.lower()}"


def image_tag(preview_id: str, ref: str) -> str:
    return f"cobble-preview/{preview_id.lower()}:{re.sub(r'[^a-z0-9_.-]', '-', ref.lower())}"


async def http_ready(url: str) -> bool:
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            return (await client.get(url)).status_code < 500
    except httpx.HTTPError:
        return False


class PreviewManager:
    def __init__(
        self,
        settings: Settings,
        engine: ContainerEngine,
        source: Source,
        *,
        ready: ReadyCheck = http_ready,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._s = settings
        self._engine = engine
        self._source = source
        self._ready = ready
        self._clock = clock
        self.records: dict[str, Record] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._reaper: asyncio.Task[None] | None = None
        self._build_slot = asyncio.Semaphore(1)
        self._wake_locks: dict[str, asyncio.Lock] = {}

    # --- persistence ------------------------------------------------------------------

    def _save(self) -> None:
        path = self._s.state_file
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps([asdict(r) for r in self.records.values()]), "utf-8")
        os.replace(tmp, path)

    def _load(self) -> None:
        path = self._s.state_file
        if not path.exists():
            return
        try:
            for item in json.loads(path.read_text("utf-8")):
                record = Record(**item)
                self.records[record.id] = record
        except (ValueError, TypeError):
            log.warning("could not read %s: starting with no previews", path)

    # --- lifecycle of the service -----------------------------------------------------

    async def start(self) -> None:
        self._s.data_dir.mkdir(parents=True, exist_ok=True)
        self._source.prepare()
        self._load()
        try:
            alive = {c.preview_id: c for c in await self._engine.list_previews() if c.running}
        except EngineError:
            log.warning("could not list the running previews", exc_info=True)
            alive = {}
        for record in self.records.values():
            if record.state == RUNNING and record.id not in alive:
                record.state = STOPPED  # woken on the next request
            elif record.state == BUILDING:
                self._schedule(record.id)  # the service died during the build: build again
        self._save()
        self._reaper = asyncio.create_task(self._reap_forever())

    async def shutdown(self) -> None:
        tasks = [*self._tasks.values(), *([self._reaper] if self._reaper else [])]
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        await self._engine.close()

    # --- API --------------------------------------------------------------------------

    def get(self, preview_id: str) -> Record | None:
        return self.records.get(preview_id)

    def view(self, record: Record) -> PreviewOut:
        public = RUNNING if record.state == STOPPED else record.state
        return PreviewOut.model_validate(
            {
                "id": record.id,
                "project_id": record.project_id,
                "milestone": record.milestone,
                "ref": record.ref,
                "state": public,
                "path": public_path(record.project_id, record.milestone),
                "detail": record.detail,
                "idle": record.state == STOPPED,
            }
        )

    async def deploy(self, request: PreviewRequest) -> Record:
        """Build and run `request.ref`. Idempotent for the same ref (unless it failed)."""
        existing = self.records.get(request.id)
        if existing and existing.ref == request.ref and existing.state != FAILED:
            existing.last_access = self._clock()
            return existing
        record = Record(
            request.id,
            str(request.project_id),
            request.milestone,
            request.ref,
            request.repo_clone_url,
            last_access=self._clock(),
        )
        if existing:
            await self._cancel(request.id)
            record.image = existing.image  # the old image is removed once the new one runs
        self.records[record.id] = record
        self._save()
        self._schedule(record.id)
        return record

    async def remove(self, preview_id: str) -> bool:
        record = self.records.pop(preview_id, None)
        await self._cancel(preview_id)
        if record is None:
            return False
        await self._drop_container(preview_id)
        if record.image:
            with contextlib.suppress(EngineError):
                await self._engine.remove_image(record.image)
        self._save()
        return True

    def touch(self, record: Record) -> None:
        record.last_access = self._clock()

    async def wake(self, record: Record) -> Record:
        """A `stopped` preview is started again from its image (one wake-up at a time)."""
        if record.state != STOPPED:
            return record
        lock = self._wake_locks.setdefault(record.id, asyncio.Lock())
        async with lock:
            if record.state != STOPPED:
                return record
            try:
                if not record.image or not await self._engine.image_exists(record.image):
                    raise EngineError("image gone")
                await self._run_container(record)
            except EngineError:
                log.warning("could not wake %s: building it again", record.id, exc_info=True)
                record.state = BUILDING
                self._save()
                self._schedule(record.id)
            return record

    # --- build and run ----------------------------------------------------------------

    def _schedule(self, preview_id: str) -> None:
        self._tasks[preview_id] = asyncio.create_task(self._build_and_run(preview_id))

    async def _cancel(self, preview_id: str) -> None:
        task = self._tasks.pop(preview_id, None)
        if task and not task.done() and task is not asyncio.current_task():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task

    async def _build_and_run(self, preview_id: str) -> None:
        record = self.records.get(preview_id)
        if record is None:
            return
        old_image = record.image
        workdir = self._s.builds_dir / preview_id
        try:
            async with self._build_slot:
                shutil.rmtree(workdir, ignore_errors=True)
                tree = workdir / "src"
                workdir.mkdir(parents=True)
                await self._source.clone(record.repo_clone_url, record.ref, tree)
                archive = workdir / "context.tar"
                self._source.pack(tree, archive)
                tag = image_tag(preview_id, record.ref)
                labels = {LABEL: "1", LABEL_ID: preview_id}
                await asyncio.wait_for(
                    self._engine.build(tag, archive, labels, self._s.build_args),
                    self._s.build_timeout_s,
                )
            record.image = tag
            await self._run_container(record)
            if old_image and old_image != tag:
                with contextlib.suppress(EngineError):
                    await self._engine.remove_image(old_image)
        except asyncio.CancelledError:
            raise
        except SourceError as exc:
            self._fail(record, exc.code if exc.code != "git_failed" else str(exc))
        except EngineError as exc:
            self._fail(record, str(exc))
        except TimeoutError:
            self._fail(record, "build_timeout")
        except Exception:
            log.exception("unexpected error while building %s", preview_id)
            self._fail(record, "internal_error")
        finally:
            shutil.rmtree(workdir, ignore_errors=True)
            self._tasks.pop(preview_id, None)

    def _fail(self, record: Record, detail: str) -> None:
        log.warning("preview %s failed: %s", record.id, detail[:200])
        record.state = FAILED
        record.detail = detail.replace(self._s.forgejo_token, "***")[-800:]
        self._save()

    def _container_body(self, record: Record) -> dict[str, object]:
        s = self._s
        return {
            "Image": record.image,
            "User": NON_ROOT,  # whatever the Dockerfile says, never root
            "Env": [f"PORT={s.container_port}", "COBBLE_DEMO=1"],
            "Labels": {LABEL: "1", LABEL_ID: record.id},
            "HostConfig": {
                "NetworkMode": s.network,
                "Memory": s.memory_mb * 1024 * 1024,
                "MemorySwap": s.memory_mb * 1024 * 1024,
                "NanoCpus": int(s.cpus * 1_000_000_000),
                "PidsLimit": s.pids,
                "ReadonlyRootfs": True,
                "CapDrop": ["ALL"],
                "SecurityOpt": ["no-new-privileges:true"],
                "Privileged": False,
                "Tmpfs": {"/tmp": f"rw,noexec,nosuid,size={s.tmp_mb}m,mode=1777"},  # noqa: S108
                "RestartPolicy": {"Name": "no"},
            },
            "NetworkingConfig": {"EndpointsConfig": {s.network: {}}},
        }

    async def _drop_container(self, preview_id: str) -> None:
        with contextlib.suppress(EngineError):
            await self._engine.remove(container_name(preview_id))

    def upstream(self, record: Record) -> str:
        return f"http://{container_name(record.id)}:{self._s.container_port}"

    async def _run_container(self, record: Record) -> None:
        await self._enforce_capacity(record.id)
        await self._drop_container(record.id)
        container_id = await self._engine.create(
            container_name(record.id), self._container_body(record)
        )
        await self._engine.start(container_id)
        deadline = self._clock() + self._s.ready_timeout_s
        while not await self._ready(self.upstream(record) + "/"):
            info = await self._engine.inspect(container_id)
            if info is None or not info.running:
                raise EngineError("the demo container exited at start-up")
            if self._clock() > deadline:
                raise EngineError("the demo did not answer in time")
            await asyncio.sleep(0.5)
        record.state = RUNNING
        record.detail = ""
        record.last_access = self._clock()
        self._save()

    async def _enforce_capacity(self, keep: str) -> None:
        running = [r for r in self.records.values() if r.state == RUNNING and r.id != keep]
        running.sort(key=lambda r: r.last_access)
        while len(running) >= self._s.max_running:
            await self._stop(running.pop(0))

    async def _stop(self, record: Record) -> None:
        await self._drop_container(record.id)
        record.state = STOPPED
        self._save()

    # --- idle stop --------------------------------------------------------------------

    async def reap_once(self) -> int:
        now = self._clock()
        idle = [
            r
            for r in self.records.values()
            if r.state == RUNNING and now - r.last_access > self._s.idle_ttl_s
        ]
        for record in idle:
            log.info("stopping idle preview %s", record.id)
            await self._stop(record)
        return len(idle)

    async def _reap_forever(self) -> None:
        while True:
            await asyncio.sleep(self._s.reap_interval_s)
            try:
                await self.reap_once()
            except Exception:
                log.exception("idle reaper failed")

    def workdir(self, preview_id: str) -> Path:
        return self._s.builds_dir / preview_id
