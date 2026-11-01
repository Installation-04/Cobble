"""scripts/step11_report.sh: read-only report for the step 11 validation."""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "step11_report.sh"


def _run(tmp_path: Path, *args: str, install: bool = True) -> subprocess.CompletedProcess[str]:
    home = tmp_path / "cobble"
    if install:
        (home / "src" / "core").mkdir(parents=True)
        (home / ".env").write_text("X=1\n", "utf-8")
        (home / "src" / "core" / "compose.yml").write_text("services: {}\n", "utf-8")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stub = bin_dir / "docker"
    # Every query answers "42": enough to see the script build the whole table.
    stub.write_text('#!/bin/sh\necho "$@" >> "$STUB_LOG"\necho 42\n', "utf-8")
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "COBBLE_DIR": str(home),
        "STUB_LOG": str(tmp_path / "docker.log"),
    }
    return subprocess.run(  # noqa: S603
        ["bash", str(SCRIPT), *args],  # noqa: S607
        env=env,
        capture_output=True,
        text=True,
    )


def test_prints_the_measurable_rows(tmp_path: Path) -> None:
    result = _run(tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("| Measure | Value |")
    for row in ("Models per role", "Real cost", "escalations", "Failed / blocked"):
        assert row in result.stdout
    assert "fill in by hand" in result.stdout


def test_only_reads_the_database(tmp_path: Path) -> None:
    _run(tmp_path)
    calls = (tmp_path / "docker.log").read_text("utf-8")
    assert "psql" in calls
    for verb in ("INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "TRUNCATE"):
        assert verb not in calls.upper().replace("UPDATED", "")


def test_refuses_a_project_name_that_could_carry_sql(tmp_path: Path) -> None:
    result = _run(tmp_path, "x'; DROP TABLE tasks; --")
    assert result.returncode == 2
    assert not (tmp_path / "docker.log").exists()


def test_fails_clearly_without_an_install(tmp_path: Path) -> None:
    result = _run(tmp_path, install=False)
    assert result.returncode == 1
    assert "no Cobble install" in result.stderr
