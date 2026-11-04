"""The sandbox for untrusted code: how it is launched, what it returns, how it is reached."""

from __future__ import annotations

import subprocess
from typing import Any

import pytest

from cobble.module_manager import sandbox as sb
from cobble.module_manager.sandbox import (
    DockerSandbox,
    FakeSandbox,
    SandboxBusy,
    SandboxError,
    SandboxResult,
    docker_argv,
)

IMAGE = "python:3.12-slim@sha256:" + "a" * 64


def option(argv: list[str], flag: str) -> str:
    return argv[argv.index(flag) + 1]


def test_the_container_is_launched_with_every_limit() -> None:
    argv = docker_argv("docker", IMAGE, "cobble-sandbox-x")
    assert option(argv, "--network") == "none"  # nothing to talk to
    assert "--read-only" in argv
    assert option(argv, "--cap-drop") == "ALL"
    assert option(argv, "--security-opt") == "no-new-privileges:true"
    assert option(argv, "--user") == "10001:10001"  # never root
    assert option(argv, "--memory") == "256m" and option(argv, "--memory-swap") == "256m"
    assert option(argv, "--cpus") == "1" and option(argv, "--pids-limit") == "64"
    assert "--rm" in argv and option(argv, "--name") == "cobble-sandbox-x"
    tmpfs = option(argv, "--tmpfs")
    assert "noexec" in tmpfs and "size=16m" in tmpfs
    # the pinned image, then the interpreter in isolated mode reading the program on stdin
    assert argv[-3:] == ["python", "-I", "-"]
    assert IMAGE in argv and argv.index(IMAGE) < argv.index("python")
    # nothing from the host and no socket
    assert "--volume" not in argv and "-v" not in argv and "--privileged" not in argv
    assert not any("docker.sock" in part for part in argv)


class Run:
    def __init__(self, result: Any = None, error: Exception | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self.result = result
        self.error = error

    def __call__(self, argv: list[str], **kw: Any) -> Any:
        self.calls.append({"argv": argv, **kw})
        if self.error is not None and argv[1] == "run":
            raise self.error
        return self.result or subprocess.CompletedProcess(argv, 0, "out", "err")


def test_the_program_goes_to_stdin_and_the_output_comes_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = Run(subprocess.CompletedProcess([], 3, "printed", "boom"))
    monkeypatch.setattr(sb.subprocess, "run", run)
    result = DockerSandbox(IMAGE).run("print(1)", 5)
    assert result == SandboxResult(3, "printed", "boom", False)
    call = run.calls[0]
    assert call["input"] == "print(1)" and call["timeout"] == 5 and call["check"] is False


def test_a_program_that_runs_too_long_is_killed_by_name(monkeypatch: pytest.MonkeyPatch) -> None:
    run = Run(error=subprocess.TimeoutExpired("docker", 5))
    monkeypatch.setattr(sb.subprocess, "run", run)
    result = DockerSandbox(IMAGE).run("while True: pass", 5)
    assert result.timed_out and result.exit_code == 124
    run_argv, kill_argv = run.calls[0]["argv"], run.calls[1]["argv"]
    assert kill_argv[:2] == ["docker", "kill"] and kill_argv[2] == option(run_argv, "--name")


def test_the_time_limit_is_clamped(monkeypatch: pytest.MonkeyPatch) -> None:
    run = Run()
    monkeypatch.setattr(sb.subprocess, "run", run)
    DockerSandbox(IMAGE).run("x", 10_000)
    DockerSandbox(IMAGE).run("x", 0)
    assert [c["timeout"] for c in run.calls] == [sb.MAX_TIMEOUT_S, 1.0]


def test_output_is_cut_so_a_program_cannot_flood_the_caller(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    big = "x" * (sb.MAX_OUTPUT_BYTES * 3)
    monkeypatch.setattr(sb.subprocess, "run", Run(subprocess.CompletedProcess([], 0, big, big)))
    result = DockerSandbox(IMAGE).run("print('x')", 5)
    assert len(result.stdout) < sb.MAX_OUTPUT_BYTES + 100 and result.stdout.endswith(
        "[output truncated]"
    )


def test_an_oversized_program_is_refused_before_docker_is_asked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = Run()
    monkeypatch.setattr(sb.subprocess, "run", run)
    with pytest.raises(SandboxError) as info:
        DockerSandbox(IMAGE).run("x" * (sb.MAX_PROGRAM_BYTES + 1), 5)
    assert info.value.code == "program_too_large" and run.calls == []


@pytest.mark.parametrize(
    ("trouble", "code"),
    [(OSError("no docker"), "docker_unavailable"), (None, "sandbox_unavailable")],
)
def test_docker_being_unavailable_is_reported_not_hidden(
    monkeypatch: pytest.MonkeyPatch, trouble: Exception | None, code: str
) -> None:
    result = None if trouble else subprocess.CompletedProcess([], 125, "", "daemon error")
    monkeypatch.setattr(sb.subprocess, "run", Run(result, error=trouble))
    with pytest.raises(SandboxError) as info:
        DockerSandbox(IMAGE).run("x", 5)
    assert info.value.code == code


def test_only_a_few_programs_run_at_once(monkeypatch: pytest.MonkeyPatch) -> None:
    box = DockerSandbox(IMAGE)
    held = [box._slots.acquire() for _ in range(sb.MAX_CONCURRENT)]
    assert all(held)
    monkeypatch.setattr(sb.subprocess, "run", Run())
    with pytest.raises(SandboxBusy):
        box.run("x", 5)
    box._slots.release()
    assert box.run("x", 5).exit_code == 0  # a slot freed: it runs again


def test_the_fake_sandbox_records_and_answers() -> None:
    fake = FakeSandbox([SandboxResult(1, "", "e", False)])
    assert fake.run("a", 1).exit_code == 1 and fake.run("b", 1).exit_code == 0
    assert fake.programs == ["a", "b"]
