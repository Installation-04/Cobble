"""Runs a short untrusted Python program in a throwaway container and returns what it printed.

The language-model benchmark scores a model by running the code it wrote; that code is
untrusted, so it never runs in the API or the worker. Only the module-manager touches Docker
(CLAUDE.md rule 5), so it offers this one small primitive: a container from a pinned image that
has no network, a read-only filesystem, no capability, an unprivileged user, and CPU, memory,
process and time limits. The program arrives on stdin and nothing from the host is mounted.
"""

from __future__ import annotations

import contextlib
import subprocess
import threading
import uuid
from dataclasses import dataclass, field
from typing import Protocol

MAX_PROGRAM_BYTES = 100_000
MAX_OUTPUT_BYTES = 64_000
MAX_TIMEOUT_S = 60.0
MAX_CONCURRENT = 2


class SandboxError(Exception):
    """The sandbox cannot run (Docker missing, image unavailable). `code` is stable."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class SandboxBusy(SandboxError):
    def __init__(self) -> None:
        super().__init__("sandbox_busy")


@dataclass(frozen=True)
class SandboxResult:
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool


class Sandbox(Protocol):
    def run(self, program: str, timeout_s: float) -> SandboxResult: ...


def clip(text: str) -> str:
    data = text.encode("utf-8", "replace")
    if len(data) <= MAX_OUTPUT_BYTES:
        return text
    return data[:MAX_OUTPUT_BYTES].decode("utf-8", "ignore") + "\n[output truncated]"


def docker_argv(docker: str, image: str, name: str) -> list[str]:
    """The `docker run` command line. Every limit is here, in one place, and tested."""
    return [
        docker,
        "run",
        "--rm",
        "--interactive",
        "--name",
        name,
        "--label",
        "cobble.sandbox=true",
        "--network",
        "none",
        "--read-only",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,size=16m",  # noqa: S108 - inside the throwaway container
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges:true",
        "--user",
        "10001:10001",
        "--memory",
        "256m",
        "--memory-swap",
        "256m",
        "--cpus",
        "1",
        "--pids-limit",
        "64",
        "--env",
        "PYTHONDONTWRITEBYTECODE=1",
        image,
        "python",
        "-I",
        "-",
    ]


@dataclass
class DockerSandbox:
    image: str
    docker: str = "docker"
    _slots: threading.BoundedSemaphore = field(
        default_factory=lambda: threading.BoundedSemaphore(MAX_CONCURRENT), repr=False
    )

    def run(self, program: str, timeout_s: float) -> SandboxResult:
        if len(program.encode("utf-8")) > MAX_PROGRAM_BYTES:
            raise SandboxError("program_too_large")
        timeout = max(1.0, min(float(timeout_s), MAX_TIMEOUT_S))
        if not self._slots.acquire(blocking=False):
            raise SandboxBusy
        name = f"cobble-sandbox-{uuid.uuid4().hex[:12]}"
        try:
            try:
                done = subprocess.run(  # noqa: S603 - fixed argv, no shell
                    docker_argv(self.docker, self.image, name),
                    input=program,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    check=False,
                )
            except subprocess.TimeoutExpired:
                self._kill(name)
                return SandboxResult(124, "", "", True)
            except OSError:
                raise SandboxError("docker_unavailable") from None
            if done.returncode == 125:  # `docker run` itself failed (daemon, image)
                raise SandboxError("sandbox_unavailable")
            return SandboxResult(done.returncode, clip(done.stdout), clip(done.stderr), False)
        finally:
            self._slots.release()

    def _kill(self, name: str) -> None:
        # `--rm` and the daemon clean up whatever this cannot reach.
        with contextlib.suppress(OSError, subprocess.TimeoutExpired):
            subprocess.run(  # noqa: S603 - fixed argv, no shell
                [self.docker, "kill", name], capture_output=True, timeout=15, check=False
            )


@dataclass
class FakeSandbox:
    """Tests only: records the programs and answers from a script."""

    results: list[SandboxResult] = field(default_factory=list)
    programs: list[str] = field(default_factory=list)
    error: SandboxError | None = None

    def run(self, program: str, timeout_s: float) -> SandboxResult:
        self.programs.append(program)
        if self.error is not None:
            raise self.error
        if self.results:
            return self.results.pop(0)
        return SandboxResult(0, "", "", False)
