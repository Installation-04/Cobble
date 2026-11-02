"""scripts/pin_images.py: pins what CI published, touches nothing else."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "pin_images", Path(__file__).resolve().parents[1] / "pin_images.py"
)
assert SPEC and SPEC.loader
pin_images = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pin_images)

OLD = "a" * 64
NEW = "b" * 64
THIRD = "c" * 64


def ref(name: str, digest: str, owner: str = "installation-04") -> str:
    return f"ghcr.io/{owner}/cobble-{name}@sha256:{digest}"


def test_a_reference_must_carry_a_digest() -> None:
    assert pin_images.parse([ref("agent-service", NEW)]) == {
        "agent-service": ref("agent-service", NEW)
    }
    for bad in (
        "ghcr.io/x/cobble-agent-service:latest",
        "docker.io/library/nginx@sha256:" + NEW,
        "x",
    ):
        with pytest.raises(ValueError):
            pin_images.parse([bad])


def test_only_the_named_images_are_replaced_whatever_their_old_tag_or_owner() -> None:
    text = (
        f"images:\n  - {ref('agent-service', OLD, 'someone')}\n"
        f"  - ghcr.io/installation-04/cobble-agent-service:0.1@sha256:{OLD}\n"
        f"  - {ref('preview-service', OLD)}\n"
        f"  - docker.io/library/nginx:1@sha256:{THIRD}\n"
    )
    out, used = pin_images.rewrite(text, {"agent-service": ref("agent-service", NEW)})
    assert used == {"agent-service"}
    assert out.count(ref("agent-service", NEW)) == 2
    assert ref("preview-service", OLD) in out and f"nginx:1@sha256:{THIRD}" in out
    assert OLD not in out.replace(ref("preview-service", OLD), "")


def test_the_catalogue_is_rewritten_in_place_and_unknown_names_are_reported(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "aider").mkdir()
    manifest = tmp_path / "aider" / "manifest.yaml"
    manifest.write_text(f"images:\n  - {ref('agent-service', OLD)}\n")
    (tmp_path / "aider" / "notes.txt").write_text(ref("agent-service", OLD))  # not a catalogue file
    pinned = pin_images.parse([ref("agent-service", NEW), ref("ghost", NEW)])
    changed, used = pin_images.pin(tmp_path, pinned)
    assert changed == [manifest] and used == {"agent-service"}
    assert NEW in manifest.read_text() and OLD in (tmp_path / "aider" / "notes.txt").read_text()
    capsys.readouterr()


def test_the_workflow_files_can_be_read_from_a_directory(tmp_path: Path) -> None:
    (tmp_path / "x").mkdir()
    (tmp_path / "x" / "agent-service.txt").write_text(ref("agent-service", NEW) + "\n")
    assert pin_images.main(["--from-dir", str(tmp_path)]) == 1  # nothing in catalog/ uses it yet
