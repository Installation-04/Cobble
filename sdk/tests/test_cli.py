"""`cobble-sdk init | lint | test`: what a module author sees."""

from __future__ import annotations

import stat
from pathlib import Path

import pytest

from cobble_sdk import cli
from cobble_sdk.cli import PLACEHOLDER_DIGEST, main

REAL = "a" * 64


def make(tmp: Path, name: str = "demo") -> Path:
    assert main(["init", name, "--dir", str(tmp)]) == 0
    return tmp / name


def pin(directory: Path) -> None:
    for file in ("manifest.yaml", "compose.yml"):
        path = directory / file
        path.write_text(path.read_text().replace(PLACEHOLDER_DIGEST, REAL))


def test_init_writes_a_module_that_needs_its_digest_pinned(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    demo = make(tmp_path)
    assert (demo / "manifest.yaml").is_file() and (demo / "compose.yml").is_file()
    assert main(["lint", str(demo), "--no-compose"]) == 1
    assert "placeholder digest" in capsys.readouterr().err
    pin(demo)
    assert main(["lint", str(demo), "--no-compose"]) == 0
    assert "demo: ok" in capsys.readouterr().out


def test_init_refuses_bad_ids_and_existing_work(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["init", "Bad_Id", "--dir", str(tmp_path)]) == 2
    make(tmp_path)
    assert main(["init", "demo", "--dir", str(tmp_path)]) == 1
    assert "not empty" in capsys.readouterr().err


def test_lint_reports_every_manifest_problem(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    demo = make(tmp_path)
    pin(demo)
    manifest = demo / "manifest.yaml"
    manifest.write_text(manifest.read_text() + "colour: blue\nlicense: ''\n")
    assert main(["lint", str(demo), "--no-compose"]) == 1
    err = capsys.readouterr().err
    assert "colour" in err and "license" in err


def test_lint_checks_files_hooks_and_the_directory_name(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    demo = make(tmp_path)
    pin(demo)
    manifest = demo / "manifest.yaml"
    manifest.write_text(manifest.read_text() + "hooks:\n  post_install: hooks/up.sh\n")
    assert main(["lint", str(demo), "--no-compose"]) == 1
    assert "hooks/up.sh: the hook does not exist" in capsys.readouterr().err
    (demo / "hooks").mkdir()
    hook = demo / "hooks" / "up.sh"
    hook.write_text("#!/bin/sh\n")
    assert main(["lint", str(demo), "--no-compose"]) == 1
    assert "not executable" in capsys.readouterr().err
    hook.chmod(hook.stat().st_mode | stat.S_IXUSR)
    assert main(["lint", str(demo), "--no-compose"]) == 0
    renamed = demo.rename(tmp_path / "other")
    assert main(["lint", str(renamed), "--no-compose"]) == 1
    assert "must match the directory name" in capsys.readouterr().err
    (renamed / "compose.yml").unlink()
    assert main(["lint", str(renamed), "--no-compose"]) == 1
    assert "compose.yml: the compose file does not exist" in capsys.readouterr().err


def test_lint_walks_a_catalogue_and_fails_if_one_module_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    pin(make(tmp_path, "good"))
    make(tmp_path, "unpinned")
    assert main(["lint", str(tmp_path), "--no-compose"]) == 1
    captured = capsys.readouterr()
    assert "good: ok" in captured.out and "unpinned: " in captured.err
    assert main(["lint", str(tmp_path / "nothing-here")]) == 2


def test_compose_rule_violations_are_problems_and_a_missing_docker_is_a_note(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    demo = make(tmp_path)
    pin(demo)
    monkeypatch.setattr(cli, "_render", lambda *_a: "docker is not installed")
    assert main(["lint", str(demo)]) == 0
    assert "not checked (docker is not installed)" in capsys.readouterr().out
    monkeypatch.setattr(
        cli,
        "_render",
        lambda *_a: {
            "services": {
                "app": {
                    "image": f"docker.io/library/nginx:1.27-alpine@sha256:{REAL}",
                    "privileged": True,
                }
            }
        },
    )
    assert main(["lint", str(demo)]) == 1
    assert "privileged" in capsys.readouterr().err


def test_test_installs_and_removes_on_every_sample_machine(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    demo = make(tmp_path)
    pin(demo)
    assert main(["test", str(demo)]) == 0
    out = capsys.readouterr().out
    assert out.count("installs (1 steps) and removes cleanly") == 5


def test_test_says_when_a_machine_cannot_run_the_module_and_when_it_cannot_be_installed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    demo = make(tmp_path)
    pin(demo)
    manifest = demo / "manifest.yaml"
    manifest.write_text(manifest.read_text() + "hardware:\n  min_ram_mb: 8192\n  gpu: nvidia\n")
    assert main(["test", str(demo)]) == 0
    out = capsys.readouterr().out
    assert "1 GB, no GPU: does not fit" in out and "16 GB, NVIDIA: installs" in out
    manifest.write_text(manifest.read_text().replace("requires: []", "requires: [nowhere]"))
    assert main(["test", str(demo)]) == 1
    assert "cannot be installed" in capsys.readouterr().err
