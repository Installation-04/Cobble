"""ComposeRunner against a stub `docker`: the commands it builds and how it reads the results."""

from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest

from cobble.module_manager.runner import ComposeRunner, RunnerError, parse_hook_output


@pytest.fixture
def docker(tmp_path: Path) -> Path:
    """A stub `docker` that logs its arguments and stdin; behaviour is set by files next to it."""
    script = tmp_path / "docker"
    script.write_text(
        "#!/bin/sh\n"
        'echo "$@" >> "$STUB_DIR/args"\n'
        '[ -t 0 ] || cat > "$STUB_DIR/stdin" 2>/dev/null\n'
        'env | grep "^COBBLE_SECRET_" > "$STUB_DIR/env" 2>/dev/null\n'
        '[ -f "$STUB_DIR/stdout" ] && cat "$STUB_DIR/stdout"\n'
        '[ -f "$STUB_DIR/exit" ] && exit "$(cat "$STUB_DIR/exit")"\n'
        "exit 0\n"
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script


@pytest.fixture(autouse=True)
def stub_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("STUB_DIR", str(tmp_path))
    return tmp_path


def test_up_pipes_the_compose_file_on_stdin_and_never_writes_it(
    docker: Path, stub_dir: Path
) -> None:
    runner = ComposeRunner(str(docker))
    compose = {"name": "cobble-x", "services": {"x": {"image": "i@sha256:" + "a" * 64}}}
    runner.up("cobble-x", compose, {"COBBLE_SECRET_TOKEN": "s3cr3t-value"})
    args = (stub_dir / "args").read_text()
    assert "compose -p cobble-x -f - up -d --wait --no-build" in args
    assert json.loads((stub_dir / "stdin").read_text()) == compose
    assert "COBBLE_SECRET_TOKEN=s3cr3t-value" in (stub_dir / "env").read_text()


def test_a_failing_docker_gives_a_code_without_any_output(docker: Path, stub_dir: Path) -> None:
    (stub_dir / "exit").write_text("1")
    (stub_dir / "stdout").write_text("password=hunter2-leak\n")
    runner = ComposeRunner(str(docker))
    with pytest.raises(RunnerError) as info:
        runner.up("cobble-x", {"services": {}}, {})
    assert info.value.code == "up_failed"
    assert "hunter2" not in f"{info.value!s}{info.value!r}"
    with pytest.raises(RunnerError) as down:
        runner.down("cobble-x", volumes=True)
    assert down.value.code == "down_failed"


def test_down_removes_volumes_only_when_asked(docker: Path, stub_dir: Path) -> None:
    runner = ComposeRunner(str(docker))
    runner.down("cobble-x", volumes=False)
    runner.down("cobble-x", volumes=True)
    first, second = (stub_dir / "args").read_text().splitlines()
    assert "--volumes" not in first
    assert "--volumes" in second
    assert "--remove-orphans" in first


def test_a_missing_docker_binary_is_reported_as_unavailable(tmp_path: Path) -> None:
    with pytest.raises(RunnerError) as info:
        ComposeRunner(str(tmp_path / "no-such-docker")).up("p", {}, {})
    assert info.value.code == "docker_unavailable"


@pytest.mark.parametrize(
    ("rows", "healthy"),
    [
        ([{"State": "running", "Health": "healthy"}, {"State": "running", "Health": ""}], True),
        ([{"State": "running", "Health": "starting"}], False),
        ([{"State": "exited", "Health": ""}], False),
        ([], False),
    ],
)
def test_wait_healthy_reads_compose_ps(
    docker: Path, stub_dir: Path, rows: list[dict[str, str]], healthy: bool
) -> None:
    (stub_dir / "stdout").write_text("\n".join(json.dumps(r) for r in rows))
    assert ComposeRunner(str(docker)).wait_healthy("cobble-x", 1.0) is healthy


def test_wait_healthy_is_false_when_ps_fails(docker: Path, stub_dir: Path) -> None:
    (stub_dir / "exit").write_text("1")
    assert ComposeRunner(str(docker)).wait_healthy("cobble-x", 1.0) is False


def test_hooks_run_with_their_environment_and_only_secret_lines_are_kept(tmp_path: Path) -> None:
    script = tmp_path / "hook.sh"
    script.write_text(
        'echo "noise that must not be kept: $COBBLE_SECRET_API"\n'
        "echo '::secret::client_id=abc12345'\n"
        "echo '::secret::client_secret=xyz98765=with=equals'\n"
        "exit 0\n"
    )
    result = ComposeRunner().run_hook(str(script), {"COBBLE_SECRET_API": "token-value-1"})
    assert result.returncode == 0
    assert result.produced_secrets == {
        "client_id": "abc12345",
        "client_secret": "xyz98765=with=equals",
    }


def test_a_failing_hook_reports_its_exit_code(tmp_path: Path) -> None:
    script = tmp_path / "hook.sh"
    script.write_text("exit 7\n")
    assert ComposeRunner().run_hook(str(script), {}).returncode == 7


def test_a_hook_that_takes_too_long_is_a_failure(tmp_path: Path) -> None:
    script = tmp_path / "hook.sh"
    script.write_text("sleep 5\n")
    assert ComposeRunner(hook_timeout_s=0.2).run_hook(str(script), {}).returncode == 124


def test_parse_hook_output_ignores_malformed_lines() -> None:
    text = "\n".join(
        ["::secret::=novalue", "::secret::onlykey", "::secret::k=", "plain", "::secret::ok=1v"]
    )
    assert parse_hook_output(text) == {"ok": "1v"}


def test_a_hook_does_not_inherit_the_managers_own_secrets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("COBBLE_DATABASE_URL", "postgresql://user:db-password@db/x")
    monkeypatch.setenv("COBBLE_MODULE_MANAGER_TOKEN", "manager-token")
    monkeypatch.setenv("COBBLE_REDIS_URL", "redis://:redis-password@r/0")
    script = tmp_path / "hook.sh"
    script.write_text("env | sort\n")
    result = ComposeRunner().run_hook(str(script), {"COBBLE_MODULE_ID": "demo"})
    assert result.returncode == 0
    # the hook's own stdout is not exposed; check through a file it writes
    out = tmp_path / "env.txt"
    script.write_text(f"env | sort > {out}\n")
    ComposeRunner().run_hook(str(script), {"COBBLE_MODULE_ID": "demo", "COBBLE_PUBLIC_URL": "u"})
    seen = out.read_text()
    assert "COBBLE_MODULE_ID=demo" in seen and "COBBLE_PUBLIC_URL=u" in seen
    for secret in ("db-password", "manager-token", "redis-password"):
        assert secret not in seen
