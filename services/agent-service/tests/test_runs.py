"""Run lifecycle against a fake Docker engine and real git repositories."""

from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path
from typing import Any

import pytest

from cobble_agent_service.config import Settings
from cobble_agent_service.runs import META, Record, RunError, RunManager

from .conftest import (
    FORGEJO_SECRET,
    RUN_TOKEN,
    Ctx,
    FakeEngine,
    finished,
    make_request,
    new_manager,
    sh,
)


async def run_to_end(
    settings: Settings, engine: FakeEngine, **over: object
) -> tuple[str, RunManager]:
    manager = new_manager(settings, engine)
    await manager.start()
    run_id = await manager.create(make_request(settings, **over))
    await finished(manager, run_id)
    return run_id, manager


async def test_successful_run_pushes_the_branch(settings: Settings, remote: Path) -> None:
    engine = FakeEngine()
    manager = new_manager(settings, engine)
    await manager.start()
    run_id = await manager.create(make_request(settings))
    await finished(manager, run_id)
    status = manager.status(run_id)
    assert status.state == "done"
    assert status.exit_code == 0
    assert status.commits == 1 and status.pushed
    assert "agent.txt" in status.diff_stat
    assert status.head_sha == sh("rev-parse", "agent/t-001", cwd=remote / "proj.git")
    assert "working" in status.log_tail
    assert engine.removed == ["c0001"]  # the container is removed once the run is over
    await manager.shutdown()


async def test_instructions_are_written_to_the_worktree_not_the_command_line(
    settings: Settings,
) -> None:
    seen: dict[str, object] = {}

    async def script(ctx: Ctx) -> int:
        seen["text"] = (ctx.work / ".cobble" / "instructions.md").read_text("utf-8")
        seen["exclude"] = (ctx.work / ".git" / "info" / "exclude").read_text("utf-8")
        seen["spec"] = ctx.spec
        ctx.commit()
        return 0

    engine = FakeEngine(script)
    await run_to_end(settings, engine, instructions="SPEC TEXT")
    assert seen["text"] == "SPEC TEXT"
    assert ".cobble/" in str(seen["exclude"])
    spec = seen["spec"]
    assert isinstance(spec, dict)
    assert "Cmd" not in spec and "Entrypoint" not in spec
    assert "SPEC TEXT" not in json.dumps(spec)


async def test_container_spec_is_locked_down(settings: Settings) -> None:
    captured: dict[str, Any] = {}

    async def script(ctx: Ctx) -> int:
        captured.update(ctx.spec)
        ctx.commit()
        return 0

    await run_to_end(settings, FakeEngine(script))
    spec = captured
    host = spec["HostConfig"]
    assert isinstance(host, dict)
    assert spec["User"] == "10001:10001"
    assert host["ReadonlyRootfs"] is True and host["Privileged"] is False
    assert host["CapDrop"] == ["ALL"]
    assert host["SecurityOpt"] == ["no-new-privileges:true"]
    assert host["NetworkMode"] == "cobble_agents"
    assert host["PidsLimit"] == 128
    assert host["Memory"] == host["MemorySwap"] == 512 * 1024 * 1024
    assert host["NanoCpus"] == 1_000_000_000
    assert "/tmp" in host["Tmpfs"]
    # Exactly one mount (the worktree) and no docker socket, no binds of host paths but it.
    mounts = host["Mounts"]
    assert len(mounts) == 1 and mounts[0]["Target"] == "/work"
    assert "docker.sock" not in json.dumps(spec)
    assert "Binds" not in host and "Devices" not in host
    env = dict(e.split("=", 1) for e in spec["Env"])
    assert env["HTTPS_PROXY"] == env["HTTP_PROXY"] == "http://agent-proxy:3128"
    assert env["OPENAI_API_BASE"] == "http://api:8000/internal/llm/v1"
    assert env["OPENAI_API_KEY"] == RUN_TOKEN
    assert env["COBBLE_MARKER"] == "[cobble-task:T-001:worker:1]"
    assert env["COBBLE_FILES"] == "hello.txt" and env["COBBLE_TEST_COMMAND"] == "pytest -q"


async def test_volume_mode_uses_a_subpath_mount(settings: Settings) -> None:
    captured: dict[str, Any] = {}

    async def script(ctx: Ctx) -> int:
        captured.update(ctx.spec)
        return 1

    from dataclasses import replace

    volume_settings = replace(settings, data_host_dir="", data_volume="agents-data")
    engine = FakeEngine(script)
    manager = new_manager(volume_settings, engine)
    await manager.start()
    # The fake needs a real path for its script, so only build the spec here.
    rec = Record("abc", "T-1", "p", "worker", "b", "main", "[m]", 3, 30)
    spec = manager.container_spec(rec, make_request(volume_settings))
    mount = spec["HostConfig"]["Mounts"][0]
    assert mount == {
        "Type": "volume",
        "Source": "agents-data",
        "Target": "/work",
        "VolumeOptions": {"Subpath": "runs/abc/work"},
    }
    await manager.shutdown()


async def test_limits_are_capped_by_the_service(settings: Settings) -> None:
    from dataclasses import replace

    s = replace(settings, cap_cpu=2.0, cap_memory_mb=1024, cap_pids=64, cap_seconds=20)
    manager = new_manager(s, FakeEngine())
    req = make_request(s, limits={"cpu": 32, "memory_mb": 65536, "pids": 9000, "max_seconds": 3000})
    rec = Record("abc", "T-1", "p", "worker", "b", "main", "[m]", 3, 20)
    host = manager.container_spec(rec, req)["HostConfig"]
    assert host["NanoCpus"] == 2_000_000_000 and host["PidsLimit"] == 64
    assert host["Memory"] == 1024 * 1024 * 1024
    run_id = await manager.create(req)
    assert manager.records[run_id].max_seconds == 20
    await finished(manager, run_id)


async def test_forgejo_token_never_reaches_the_container_or_the_repository(
    settings: Settings, tmp_path: Path
) -> None:
    captured: dict[str, Any] = {}

    async def script(ctx: Ctx) -> int:
        captured["spec"] = json.dumps(ctx.spec)
        captured["config"] = (ctx.work / ".git" / "config").read_text("utf-8")
        ctx.commit()
        return 0

    run_id, _ = await run_to_end(settings, FakeEngine(script))
    assert FORGEJO_SECRET not in str(captured["spec"])
    assert FORGEJO_SECRET not in str(captured["config"])
    run_dir = settings.runs_dir / run_id
    for path in run_dir.rglob("*"):
        if path.is_file() and ".git/objects" not in str(path):
            assert FORGEJO_SECRET.encode() not in path.read_bytes(), path
    assert FORGEJO_SECRET not in (run_dir / "repo.git" / "config").read_text("utf-8")
    # The run token is a secret too: it must not be persisted by agent-service.
    assert RUN_TOKEN not in (run_dir / META).read_text("utf-8")
    assert "x-access-token" not in (run_dir / "work" / ".git" / "config").read_text("utf-8")


def test_git_credentials_only_for_authenticated_commands(settings: Settings) -> None:
    from cobble_agent_service.gitops import GitOps

    git = GitOps(settings)
    plain = git._env(auth=False)
    authed = git._env(auth=True)
    assert FORGEJO_SECRET not in " ".join(plain.values())
    assert authed["COBBLE_GIT_TOKEN"] == FORGEJO_SECRET
    assert authed["GIT_ASKPASS"].endswith(".askpass.sh")
    git.prepare_environment()
    assert os.stat(authed["GIT_ASKPASS"]).st_mode & 0o077 == 0  # private to the service user
    assert FORGEJO_SECRET not in Path(authed["GIT_ASKPASS"]).read_text("utf-8")


async def test_clone_url_outside_the_forge_is_refused(settings: Settings) -> None:
    manager = new_manager(settings, FakeEngine())
    with pytest.raises(RunError) as err:
        await manager.create(make_request(settings, repo_clone_url="http://evil.example/x.git"))
    assert err.value.status == 400 and err.value.code == "repo_url_not_allowed"


async def test_public_url_is_rewritten_to_the_internal_one(settings: Settings) -> None:
    from dataclasses import replace

    from cobble_agent_service.gitops import GitOps

    s = replace(
        settings,
        git_rewrite_from="http://localhost/git/",
        git_rewrite_to=settings.forgejo_url + "/",
    )
    assert (
        GitOps(s).resolve_url("http://localhost/git/proj.git") == f"{settings.forgejo_url}/proj.git"
    )


async def test_network_must_be_internal(settings: Settings) -> None:
    engine = FakeEngine(internal=False)
    _, manager = await run_to_end(settings, engine)
    rec = next(iter(manager.records.values()))
    assert rec.state == "failed" and rec.reason == "agent_network_not_internal"
    assert engine.created == 0


async def test_non_zero_exit_is_failed_and_nothing_is_pushed(
    settings: Settings, remote: Path
) -> None:
    async def script(ctx: Ctx) -> int:
        ctx.commit()
        return 3

    run_id, manager = await run_to_end(settings, FakeEngine(script))
    status = manager.status(run_id)
    assert status.state == "failed" and status.exit_code == 3 and not status.pushed
    assert status.reason == "agent_failed"
    with pytest.raises(Exception):  # noqa: B017 - branch absent on the remote
        sh("rev-parse", "agent/t-001", cwd=remote / "proj.git")


async def test_exit_zero_without_commits_is_failed(settings: Settings) -> None:
    async def script(ctx: Ctx) -> int:
        return 0

    run_id, manager = await run_to_end(settings, FakeEngine(script))
    status = manager.status(run_id)
    assert status.state == "failed" and status.reason == "no_commits"


async def test_rewritten_history_is_refused(settings: Settings) -> None:
    async def script(ctx: Ctx) -> int:
        sh(
            "-c",
            "user.name=a",
            "-c",
            "user.email=a@b",
            "commit",
            "-q",
            "--amend",
            "-m",
            "x",
            cwd=ctx.work,
        )
        return 0

    run_id, manager = await run_to_end(settings, FakeEngine(script))
    status = manager.status(run_id)
    assert status.state == "failed" and status.reason == "history_rewritten"


async def test_hostile_git_config_in_the_worktree_is_not_executed(
    settings: Settings, tmp_path: Path
) -> None:
    """The agent controls .git/config and hooks; agent-service must never run them."""
    marker = tmp_path / "pwned"

    async def script(ctx: Ctx) -> int:
        ctx.commit()
        config = ctx.work / ".git" / "config"
        config.write_text(
            config.read_text("utf-8")
            + f"\n[core]\n\tfsmonitor = touch {marker}\n\tsshCommand = touch {marker}\n"
            + f"[credential]\n\thelper = !touch {marker}\n"
            + f"[uploadpack]\n\tpackObjectsHook = touch {marker}\n",
            "utf-8",
        )
        hooks = ctx.work / ".git" / "hooks"
        hooks.mkdir(exist_ok=True)
        for name in ("pre-push", "post-checkout", "reference-transaction", "pre-auto-gc"):
            hook = hooks / name
            hook.write_text(f"#!/bin/sh\ntouch {marker}\n", "utf-8")
            hook.chmod(0o755)
        return 0

    run_id, manager = await run_to_end(settings, FakeEngine(script))
    assert manager.status(run_id).state == "done"
    assert not marker.exists()


async def test_existing_task_branch_is_continued(settings: Settings, remote: Path) -> None:
    first, manager = await run_to_end(settings, FakeEngine())
    first_head = manager.status(first).head_sha

    async def script(ctx: Ctx) -> int:
        assert (ctx.work / "agent.txt").exists()  # work of the previous attempt is there
        ctx.commit("second.txt")
        return 0

    second, manager2 = await run_to_end(settings, FakeEngine(script))
    status = manager2.status(second)
    assert status.state == "done" and status.commits == 1
    assert sh("rev-parse", "agent/t-001~1", cwd=remote / "proj.git") == first_head


async def test_timeout_kills_the_container(settings: Settings) -> None:
    async def script(ctx: Ctx) -> int:
        ctx.emit("start\n")
        await asyncio.sleep(60)
        return 0

    from dataclasses import replace

    engine = FakeEngine(script)
    manager = new_manager(replace(settings, cap_seconds=1), engine)  # wall clock capped at 1 s
    await manager.start()
    run_id = await manager.create(make_request(settings))
    await finished(manager, run_id)
    status = manager.status(run_id)
    assert status.state == "timeout" and status.exit_code == 137
    assert engine.killed
    await manager.shutdown()


async def test_stop_kills_and_reports_stopped(settings: Settings) -> None:
    async def script(ctx: Ctx) -> int:
        ctx.emit("start\n")
        await asyncio.sleep(60)
        return 0

    engine = FakeEngine(script)
    manager = new_manager(settings, engine)
    await manager.start()
    run_id = await manager.create(make_request(settings))
    await asyncio.sleep(0.5)
    await manager.stop(run_id)
    await finished(manager, run_id)
    assert manager.status(run_id).state == "stopped"
    await manager.stop(run_id)  # idempotent once finished
    with pytest.raises(RunError):
        await manager.stop("missing")
    await manager.shutdown()


async def test_repeated_output_is_a_loop(settings: Settings) -> None:
    async def script(ctx: Ctx) -> int:
        for _ in range(100):
            ctx.emit("I will try again\n")
            await asyncio.sleep(0.01)
        return 0

    run_id, manager = await run_to_end(settings, FakeEngine(script))
    status = manager.status(run_id)
    assert status.state == "loop_detected" and status.reason == "repeated_line"


async def test_same_test_failure_twice_is_a_loop(settings: Settings) -> None:
    async def script(ctx: Ctx) -> int:
        for n in (1, 2, 3):
            ctx.emit(f"[cobble:test-run {n}]\n[cobble:test-fail abcd1234]\n")
            await asyncio.sleep(0.05)
        await asyncio.sleep(60)
        return 0

    run_id, manager = await run_to_end(settings, FakeEngine(script))
    status = manager.status(run_id)
    assert status.state == "loop_detected" and status.reason == "same_failure"
    assert status.iterations == 2


async def test_max_iterations_ends_the_run(settings: Settings) -> None:
    async def script(ctx: Ctx) -> int:
        for n in range(1, 10):
            ctx.emit(f"[cobble:test-run {n}]\n[cobble:test-fail {n:08d}]\n")
            await asyncio.sleep(0.05)
        await asyncio.sleep(60)
        return 0

    limits = {"max_iterations": 3, "max_seconds": 30, "cpu": 1, "memory_mb": 512, "pids": 64}
    run_id, manager = await run_to_end(settings, FakeEngine(script), limits=limits)
    status = manager.status(run_id)
    assert status.state == "failed" and status.reason == "max_iterations"
    assert status.iterations == 4


async def test_too_many_runs_is_rejected(settings: Settings) -> None:
    from dataclasses import replace

    async def script(ctx: Ctx) -> int:
        await asyncio.sleep(60)
        return 0

    manager = new_manager(replace(settings, max_runs=1), FakeEngine(script))
    await manager.start()
    first = await manager.create(make_request(settings))
    with pytest.raises(RunError) as err:
        await manager.create(make_request(settings, branch="agent/other"))
    assert err.value.status == 429
    await manager.stop(first)
    await finished(manager, first)
    await manager.shutdown()


async def test_log_endpoint_offsets(settings: Settings) -> None:
    run_id, manager = await run_to_end(settings, FakeEngine())
    data, nxt = manager.read_logs(run_id, 0)
    assert b"working" in data and nxt == len(data)
    more, nxt2 = manager.read_logs(run_id, nxt)
    assert more == b"" and nxt2 == nxt
    part, nxt3 = manager.read_logs(run_id, 0, limit=3)
    assert nxt3 == len(part) <= 3


async def test_log_chunks_do_not_split_utf8(settings: Settings) -> None:
    async def script(ctx: Ctx) -> int:
        ctx.emit("é" * 10 + "\n")
        ctx.commit()
        return 0

    run_id, manager = await run_to_end(settings, FakeEngine(script))
    chunk, nxt = manager.read_logs(run_id, 0, limit=len(b"[cobble") + 0)
    start = (settings.runs_dir / run_id / "agent.log").read_bytes().index("é".encode())
    chunk, nxt = manager.read_logs(run_id, 0, limit=start + 3)
    chunk.decode("utf-8")  # no exception: cut on a character boundary
    assert nxt == len(chunk)


async def test_retention_removes_old_finished_runs(settings: Settings) -> None:
    run_id, manager = await run_to_end(settings, FakeEngine())
    assert manager.cleanup() == []
    removed = manager.cleanup(now=time.time() + 25 * 3600)
    assert removed == [run_id]
    assert not (settings.runs_dir / run_id).exists()
    with pytest.raises(RunError):
        manager.get(run_id)


async def test_cleanup_handles_read_only_files_made_by_the_agent(settings: Settings) -> None:
    async def script(ctx: Ctx) -> int:
        ctx.commit()
        locked = ctx.work / "locked"
        locked.mkdir()
        (locked / "f").write_text("x", "utf-8")
        (locked / "f").chmod(0o400)
        locked.chmod(0o500)
        return 0

    run_id, manager = await run_to_end(settings, FakeEngine(script))
    manager.cleanup(now=time.time() + 25 * 3600)
    assert not (settings.runs_dir / run_id).exists()


# --- restart recovery ---------------------------------------------------------------------


async def test_finished_runs_survive_a_restart(settings: Settings) -> None:
    run_id, manager = await run_to_end(settings, FakeEngine())
    before = manager.status(run_id)
    again = new_manager(settings, FakeEngine())
    await again.start()
    after = again.status(run_id)
    assert after.state == "done" and after.head_sha == before.head_sha
    assert after.log_tail == before.log_tail
    await again.shutdown()


async def test_running_run_is_reattached_after_a_restart(settings: Settings) -> None:
    gate = asyncio.Event()

    async def script(ctx: Ctx) -> int:
        ctx.emit("before restart\n")
        await gate.wait()
        ctx.emit("after restart\n")
        ctx.commit()
        return 0

    engine = FakeEngine(script)
    first = new_manager(settings, engine)
    await first.start()
    run_id = await first.create(make_request(settings))
    await asyncio.sleep(0.5)
    await first.shutdown()  # service stops; the container keeps running
    assert json.loads((settings.runs_dir / run_id / META).read_text("utf-8"))["state"] == "running"
    assert engine.removed == [] and engine.killed == []

    second = new_manager(settings, engine)
    await second.start()
    assert second.status(run_id).state == "running"
    gate.set()
    await finished(second, run_id)
    status = second.status(run_id)
    assert status.state == "done" and status.pushed
    log = (settings.runs_dir / run_id / "agent.log").read_text("utf-8")
    assert log.count("before restart") == 1 and log.count("after restart") == 1
    await second.shutdown()


async def test_run_whose_container_is_gone_is_marked_failed(settings: Settings) -> None:
    engine = FakeEngine()
    first = new_manager(settings, engine)
    await first.start()

    async def stuck(ctx: Ctx) -> int:
        await asyncio.sleep(60)
        return 0

    engine.script = stuck
    run_id = await first.create(make_request(settings))
    await asyncio.sleep(0.5)
    await first.shutdown()
    engine.containers.clear()  # the container vanished while the service was down
    second = new_manager(settings, engine)
    await second.start()
    await finished(second, run_id)
    assert second.status(run_id).state == "failed"
    assert second.records[run_id].reason == "container_lost"
    await second.shutdown()


async def test_run_interrupted_while_preparing_is_marked_failed(settings: Settings) -> None:
    rec = Record("deadbeef", "T-1", "p", "worker", "b", "main", "[m]", 3, 30)
    (settings.runs_dir / rec.run_id).mkdir(parents=True)
    from dataclasses import asdict

    (settings.runs_dir / rec.run_id / META).write_text(json.dumps(asdict(rec)), "utf-8")
    manager = new_manager(settings, FakeEngine())
    await manager.start()
    await finished(manager, rec.run_id)
    assert manager.records[rec.run_id].state == "failed"
    assert manager.records[rec.run_id].reason == "interrupted"
    await manager.shutdown()


async def test_orphan_containers_are_removed_at_startup(settings: Settings) -> None:
    engine = FakeEngine()
    cid = await engine.create(
        "orphan",
        {"Labels": {"cobble.run_id": "nobody"}, "HostConfig": {"Mounts": [{"Source": "/x"}]}},
    )
    manager = new_manager(settings, engine)
    await manager.start()
    assert cid in engine.removed
    await manager.shutdown()


async def test_a_crashed_metadata_file_is_ignored(settings: Settings) -> None:
    bad = settings.runs_dir / "broken"
    bad.mkdir(parents=True)
    (bad / META).write_text("{not json", "utf-8")
    manager = new_manager(settings, FakeEngine())
    await manager.start()
    assert manager.records == {}
    await manager.shutdown()
