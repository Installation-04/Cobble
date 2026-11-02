"""Run lifecycle: prepare a worktree, start the sandboxed container, supervise it, push."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import shutil
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .config import Settings
from .detector import LoopDetector
from .engine import LABEL, LABEL_RUN, ContainerEngine, EngineError
from .gitops import GitError, GitOps
from .models import TERMINAL_STATES, RunRequest, RunStatus

log = logging.getLogger("cobble.agent_service")

RUNNER_UID = 10001
LOG_TAIL_BYTES = 4000
META = "meta.json"
LOG = "agent.log"


class RunError(RuntimeError):
    """Raised for API-level problems (maps to an HTTP error)."""

    def __init__(self, status: int, code: str, params: dict[str, Any] | None = None) -> None:
        super().__init__(code)
        self.status = status
        self.code = code
        self.params = params or {}


@dataclass
class Record:
    """Run metadata persisted as JSON. It never contains the run token or git credentials."""

    run_id: str
    task_id: str
    project_id: str
    role: str
    branch: str
    base_branch: str
    marker: str
    max_iterations: int
    max_seconds: int
    state: str = "running"
    phase: str = "preparing"  # preparing | running | finalizing | finished
    iterations: int = 0
    exit_code: int | None = None
    head_sha: str | None = None
    base_sha: str | None = None
    reason: str | None = None
    commits: int = 0
    diff_stat: str = ""
    pushed: bool = False
    container_id: str | None = None
    started_at: float = field(default_factory=time.time)
    deadline: float | None = None
    finished_at: float | None = None
    stop_requested: bool = False


class RunManager:
    def __init__(self, settings: Settings, engine: ContainerEngine, git: GitOps) -> None:
        self.s = settings
        self.engine = engine
        self.git = git
        self.records: dict[str, Record] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._stops: dict[str, asyncio.Event] = {}
        self._janitor: asyncio.Task[None] | None = None
        self._network_ok: bool | None = None

    # --- paths ---------------------------------------------------------------------------

    def run_dir(self, run_id: str) -> Path:
        return self.s.runs_dir / run_id

    def _save(self, rec: Record) -> None:
        path = self.run_dir(rec.run_id) / META
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(rec)), "utf-8")
        os.replace(tmp, path)

    # --- startup / shutdown --------------------------------------------------------------

    async def start(self) -> None:
        self.git.prepare_environment()
        for meta in sorted(self.s.runs_dir.glob(f"*/{META}")):
            try:
                rec = Record(**json.loads(meta.read_text("utf-8")))
            except (OSError, ValueError, TypeError):
                log.warning("ignoring unreadable run metadata %s", meta)
                continue
            self.records[rec.run_id] = rec
        try:
            containers = await self.engine.list_agent_containers()
        except EngineError as exc:
            log.warning("cannot list containers at startup: %s", exc)
            containers = []
        known = {r.run_id for r in self.records.values() if r.state == "running"}
        for container in containers:
            if container.run_id not in known:  # no metadata: nobody supervises it
                log.warning("removing orphan agent container %s", container.id[:12])
                with contextlib.suppress(EngineError):
                    await self.engine.kill(container.id)
                    await self.engine.remove(container.id)
        for rec in self.records.values():
            if rec.state == "running":
                self._spawn(rec, None)
        self._janitor = asyncio.create_task(self._janitor_loop())

    async def shutdown(self) -> None:
        """Stop supervising. Running containers are left alone: a restarted service picks
        them up again from the metadata and the container labels."""
        if self._janitor:
            self._janitor.cancel()
        for task in list(self._tasks.values()):
            task.cancel()
        await asyncio.gather(*self._tasks.values(), return_exceptions=True)
        if self._janitor:
            await asyncio.gather(self._janitor, return_exceptions=True)
        await self.engine.close()

    # --- API operations ------------------------------------------------------------------

    def running_count(self) -> int:
        return sum(1 for r in self.records.values() if r.state == "running")

    async def create(self, req: RunRequest) -> str:
        if self.running_count() >= self.s.max_runs:
            raise RunError(429, "too_many_runs", {"max": self.s.max_runs})
        try:
            self.git.resolve_url(req.repo_clone_url)
        except GitError as exc:
            raise RunError(400, exc.code) from None
        run_id = uuid.uuid4().hex
        rec = Record(
            run_id=run_id,
            task_id=req.task_id,
            project_id=req.project_id,
            role=req.role,
            branch=req.branch,
            base_branch=req.base_branch,
            marker=req.marker,
            max_iterations=req.limits.max_iterations,
            max_seconds=min(req.limits.max_seconds, self.s.cap_seconds),
        )
        rec.deadline = rec.started_at + rec.max_seconds
        self.run_dir(run_id).mkdir(parents=True)
        self._save(rec)
        self.records[run_id] = rec
        self._spawn(rec, req)
        return run_id

    def _spawn(self, rec: Record, req: RunRequest | None) -> None:
        self._stops[rec.run_id] = asyncio.Event()
        task = asyncio.create_task(self._execute(rec, req), name=f"run-{rec.run_id}")
        self._tasks[rec.run_id] = task
        run_id = rec.run_id
        task.add_done_callback(lambda _t: self._tasks.pop(run_id, None))

    def get(self, run_id: str) -> Record:
        rec = self.records.get(run_id)
        if rec is None:
            raise RunError(404, "run_not_found")
        return rec

    def status(self, run_id: str) -> RunStatus:
        rec = self.get(run_id)
        return RunStatus(
            run_id=rec.run_id,
            state=rec.state,  # type: ignore[arg-type]
            iterations=rec.iterations,
            exit_code=rec.exit_code,
            head_sha=rec.head_sha,
            log_tail=self.log_tail(run_id),
            reason=rec.reason,
            commits=rec.commits,
            diff_stat=rec.diff_stat,
            pushed=rec.pushed,
            started_at=rec.started_at,
            finished_at=rec.finished_at,
        )

    def log_tail(self, run_id: str) -> str:
        path = self.run_dir(run_id) / LOG
        try:
            with path.open("rb") as fh:
                fh.seek(0, os.SEEK_END)
                size = fh.tell()
                fh.seek(max(0, size - LOG_TAIL_BYTES))
                return fh.read().decode("utf-8", errors="replace")
        except OSError:
            return ""

    def read_logs(self, run_id: str, offset: int, limit: int = 1_000_000) -> tuple[bytes, int]:
        self.get(run_id)
        path = self.run_dir(run_id) / LOG
        try:
            with path.open("rb") as fh:
                fh.seek(max(0, offset))
                data = fh.read(limit)
        except OSError:
            return b"", max(0, offset)
        # Do not cut a multi-byte UTF-8 character in the middle.
        if len(data) == limit:
            for back in range(1, 4):
                try:
                    data[: len(data) - back + 1].decode("utf-8")
                    data = data[: len(data) - back + 1]
                    break
                except UnicodeDecodeError:
                    continue
        return data, max(0, offset) + len(data)

    async def stop(self, run_id: str) -> None:
        rec = self.get(run_id)
        if rec.state != "running":
            return
        rec.stop_requested = True
        self._save(rec)
        event = self._stops.get(run_id)
        if event:
            event.set()

    # --- execution -----------------------------------------------------------------------

    async def _execute(self, rec: Record, req: RunRequest | None) -> None:
        outcome = "failed"
        try:
            if rec.phase == "preparing":
                if req is not None:
                    await self._prepare(rec, req)
                else:  # restarted while preparing: only resumable if the container exists
                    found = await self._find_container(rec.run_id)
                    if found is None:
                        raise RunError(500, "interrupted")
                    rec.container_id, rec.phase = found, "running"
            if rec.phase == "running":
                outcome = await self._supervise(rec)
                rec.phase = "finalizing"
                self._save(rec)
            if rec.phase == "finalizing":
                await self._finalize(rec, outcome)
        except asyncio.CancelledError:
            raise  # service shutdown: leave the metadata as is, recovery will resume
        except GitError as exc:
            log.warning("run %s: %s", rec.run_id, exc.code)
            self._log_line(rec, f"[cobble:error] {exc.code} {exc.detail}".strip())
            await self._end(rec, "failed", exc.code)
        except (EngineError, RunError, OSError) as exc:
            log.warning("run %s: %s", rec.run_id, type(exc).__name__)
            code = exc.code if isinstance(exc, RunError) else "runtime_error"
            self._log_line(rec, f"[cobble:error] {code}")
            await self._end(rec, "failed", code)
        except Exception:
            log.exception("run %s crashed", rec.run_id)
            await self._end(rec, "failed", "internal_error")

    def _log_line(self, rec: Record, text: str) -> None:
        with (self.run_dir(rec.run_id) / LOG).open("ab") as fh:
            fh.write((text + "\n").encode("utf-8", errors="replace"))

    async def _find_container(self, run_id: str) -> str | None:
        for c in await self.engine.list_agent_containers():
            if c.run_id == run_id:
                return c.id
        return None

    async def _check_network(self) -> None:
        if self._network_ok is None:
            self._network_ok = await self.engine.network_is_internal(self.s.network)
        if not self._network_ok:
            self._network_ok = None
            raise RunError(500, "agent_network_not_internal")

    def container_spec(self, rec: Record, req: RunRequest) -> dict[str, Any]:
        s = self.s
        limits = req.limits
        cpu = min(limits.cpu, s.cap_cpu)
        mem = min(limits.memory_mb, s.cap_memory_mb) * 1024 * 1024
        pids = min(limits.pids, s.cap_pids)
        rel = f"runs/{rec.run_id}/work"
        mount: dict[str, Any]
        if s.data_volume:
            mount = {
                "Type": "volume",
                "Source": s.data_volume,
                "Target": "/work",
                "VolumeOptions": {"Subpath": rel},
            }
        else:
            mount = {"Type": "bind", "Source": f"{s.data_host_dir}/{rel}", "Target": "/work"}
        tmpfs = f"rw,nosuid,nodev,size={s.tmp_mb}m,uid={RUNNER_UID},gid={RUNNER_UID},mode=700"
        env = {
            "HTTP_PROXY": s.proxy_url,
            "HTTPS_PROXY": s.proxy_url,
            "http_proxy": s.proxy_url,
            "https_proxy": s.proxy_url,
            "NO_PROXY": s.no_proxy,
            "no_proxy": s.no_proxy,
            "OPENAI_API_BASE": s.api_url,
            "OPENAI_API_KEY": req.run_token,  # the run token: the only secret the agent holds
            "COBBLE_MARKER": req.marker,
            "COBBLE_INSTRUCTIONS_FILE": "/work/.cobble/instructions.md",
            "COBBLE_FILES": "\n".join(req.files),
            "COBBLE_TEST_COMMAND": req.test_command,
            "COBBLE_MAX_ITERATIONS": str(limits.max_iterations),
            "COBBLE_MODEL": req.model,
            "COBBLE_TASK_ID": req.task_id,
            "COBBLE_ROLE": req.role,
        }
        if s.agent_cmd:
            env["COBBLE_AGENT_CMD"] = s.agent_cmd
        return {
            "Image": s.runner_image,
            "User": f"{RUNNER_UID}:{RUNNER_UID}",
            "Env": [f"{k}={v}" for k, v in env.items()],
            "WorkingDir": "/work",
            "Tty": True,
            "Labels": {LABEL: "1", LABEL_RUN: rec.run_id, "cobble.task_id": rec.task_id},
            "HostConfig": {
                "Init": True,
                "Privileged": False,
                "ReadonlyRootfs": True,
                "CapDrop": ["ALL"],
                "SecurityOpt": ["no-new-privileges:true"],
                "NanoCpus": int(cpu * 1_000_000_000),
                "Memory": mem,
                "MemorySwap": mem,
                "PidsLimit": pids,
                "IpcMode": "private",
                "RestartPolicy": {"Name": "no"},
                "NetworkMode": s.network,
                "Tmpfs": {"/tmp": tmpfs},  # noqa: S108
                "Mounts": [mount],
                "LogConfig": {"Type": "json-file", "Config": {"max-size": "10m", "max-file": "2"}},
            },
            "NetworkingConfig": {"EndpointsConfig": {s.network: {}}},
        }

    async def _prepare(self, rec: Record, req: RunRequest) -> None:
        await self._check_network()
        run_dir = self.run_dir(rec.run_id)
        url = self.git.resolve_url(req.repo_clone_url)
        instructions = req.instructions
        rec.base_sha = await self.git.prepare_workspace(
            run_dir, url, req.base_branch, req.branch, instructions
        )
        # The agent user must be able to write the worktree (agent-service runs as the same uid).
        spec = self.container_spec(rec, req)
        rec.container_id = await self.engine.create(f"cobble-agent-{rec.run_id[:12]}", spec)
        rec.phase = "running"
        rec.started_at = time.time()
        rec.deadline = rec.started_at + rec.max_seconds
        self._save(rec)

    async def _supervise(self, rec: Record) -> str:
        """Run the container to completion. Returns the outcome label."""
        container_id = rec.container_id or await self._find_container(rec.run_id)
        if container_id is None:
            rec.reason = "container_lost"
            return "failed"
        rec.container_id = container_id
        info = await self.engine.inspect(container_id)
        if info is None:
            rec.reason = "container_lost"
            return "failed"
        if info.status == "created":
            await self.engine.start(container_id)
        stop = self._stops[rec.run_id]
        if rec.stop_requested:
            stop.set()

        detector = LoopDetector(self.s.loop_threshold)
        log_path = self.run_dir(rec.run_id) / LOG
        already = log_path.stat().st_size if log_path.exists() else 0
        if already:  # restart recovery: replay what was already captured
            detector.feed(log_path.read_bytes())
        trigger = asyncio.Event()
        reason: dict[str, str] = {}

        async def follow() -> None:
            skip = already
            written = already
            truncated = False
            with log_path.open("ab") as out:
                async for chunk in self.engine.logs(container_id):
                    if skip:
                        cut = min(skip, len(chunk))
                        chunk, skip = chunk[cut:], skip - cut
                        if not chunk:
                            continue
                    if written < self.s.log_limit_bytes:
                        out.write(chunk)
                        out.flush()
                        written += len(chunk)
                    elif not truncated:
                        out.write(b"\n[cobble:log-truncated]\n")
                        truncated = True
                    signal = detector.feed(chunk)
                    rec.iterations = max(rec.iterations, signal.iterations)
                    if signal.loop and "why" not in reason:
                        reason["why"] = "loop"
                        reason["detail"] = signal.loop
                        trigger.set()
                    elif rec.iterations > rec.max_iterations and "why" not in reason:
                        reason["why"] = "max_iterations"
                        trigger.set()

        async def waiter() -> int:
            return await self.engine.wait(container_id)

        follower = asyncio.create_task(follow())
        wait_task = asyncio.create_task(waiter())
        stop_task = asyncio.create_task(stop.wait())
        trigger_task = asyncio.create_task(trigger.wait())
        outcome = "exit"
        try:
            remaining = max(0.0, (rec.deadline or time.time()) - time.time())
            done, _ = await asyncio.wait(
                {wait_task, stop_task, trigger_task},
                timeout=remaining,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if wait_task in done:
                rec.exit_code = wait_task.result()
            else:
                if not done:
                    outcome = "timeout"
                elif stop_task in done:
                    outcome = "stopped"
                else:
                    outcome = reason.get("why", "loop")
                    rec.reason = reason.get("detail") or outcome
                with contextlib.suppress(EngineError):
                    await self.engine.kill(container_id)
                rec.exit_code = await asyncio.wait_for(wait_task, 30)
            # Drain the rest of the output before closing the log.
            with contextlib.suppress(TimeoutError, EngineError):
                await asyncio.wait_for(follower, 15)
        finally:
            for t in (follower, wait_task, stop_task, trigger_task):
                if not t.done():
                    t.cancel()
            await asyncio.gather(
                follower, wait_task, stop_task, trigger_task, return_exceptions=True
            )
        self._save(rec)
        return outcome

    async def _finalize(self, rec: Record, outcome: str) -> None:
        run_dir = self.run_dir(rec.run_id)
        state, reason = "failed", rec.reason
        collected = None
        if rec.base_sha:
            try:
                collected = await self.git.collect(run_dir, rec.branch, rec.base_sha)
                rec.head_sha = collected.head_sha
                rec.commits = collected.commits
                rec.diff_stat = collected.diff_stat
            except GitError as exc:
                if outcome == "exit" and rec.exit_code == 0:
                    reason = exc.code
        if outcome == "stopped":
            state = "stopped"
        elif outcome == "timeout":
            state = "timeout"
        elif outcome == "loop":
            state = "loop_detected"
        elif outcome == "max_iterations":
            state, reason = "failed", "max_iterations"
        elif outcome == "exit":
            if rec.exit_code != 0:
                state, reason = "failed", reason or "agent_failed"
            elif collected is None:
                state = "failed"
            elif collected.commits == 0:
                state, reason = "failed", "no_commits"
            else:
                try:
                    await self.git.push(run_dir, rec.branch)
                except GitError as exc:
                    self._log_line(rec, f"[cobble:error] {exc.code} {exc.detail}")
                    state, reason = "failed", "push_failed"
                else:
                    rec.pushed = True
                    state, reason = "done", None
        elif reason is None:
            reason = "agent_failed"
        await self._end(rec, state, reason)

    async def _end(self, rec: Record, state: str, reason: str | None) -> None:
        rec.state, rec.reason = state, reason
        rec.phase = "finished"
        rec.finished_at = time.time()
        self._save(rec)
        self._log_line(rec, f"[cobble:end] state={state}" + (f" reason={reason}" if reason else ""))
        if rec.container_id:
            with contextlib.suppress(EngineError):
                await self.engine.remove(rec.container_id)
        self._stops.pop(rec.run_id, None)

    # --- retention -----------------------------------------------------------------------

    async def _janitor_loop(self) -> None:
        while True:
            try:
                self.cleanup()
            except Exception:
                log.exception("cleanup failed")
            await asyncio.sleep(600)

    def cleanup(self, now: float | None = None) -> list[str]:
        """Delete finished runs older than the retention period. Returns removed run ids."""
        now = time.time() if now is None else now
        removed: list[str] = []
        for run_id, rec in list(self.records.items()):
            if rec.state not in TERMINAL_STATES or rec.finished_at is None:
                continue
            if now - rec.finished_at < self.s.retention_hours * 3600:
                continue
            shutil.rmtree(self.run_dir(run_id), onerror=_force_remove)
            del self.records[run_id]
            removed.append(run_id)
        return removed


def _force_remove(func: Any, path: str, _exc: Any) -> None:
    """rmtree helper: the agent may have created read-only files or directories."""
    with contextlib.suppress(OSError):
        os.chmod(os.path.dirname(path), 0o700)
        os.chmod(path, 0o700)
        func(path)
