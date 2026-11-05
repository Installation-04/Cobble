"""scripts/make_release_compose.py and make_release_bundle.sh: the assets of a release."""

from __future__ import annotations

import hashlib
import importlib.util
import shutil
import subprocess
import tarfile
from pathlib import Path

import pytest
import yaml

SCRIPTS = Path(__file__).resolve().parents[1]
REPO = SCRIPTS.parent
SPEC = importlib.util.spec_from_file_location(
    "make_release_compose", SCRIPTS / "make_release_compose.py"
)
assert SPEC and SPEC.loader
mrc = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mrc)

D = "a" * 64
COMPOSE = {
    "services": {
        "postgres": {"image": "postgres:16"},
        "worker": {"build": {"context": "../backend"}},
        "api": {"build": "../backend"},
        "module-manager": {"profiles": ["modules"], "build": {"context": "../backend"}},
    }
}


def digests(*names: str) -> dict[str, str]:
    return dict.fromkeys(names, f"sha256:{D}")


def test_every_built_service_is_pinned_sorted_and_lower_cased() -> None:
    text = mrc.generate(
        COMPOSE, "Installation-04", "v1.2.3", digests("api", "worker", "module-manager")
    )
    parsed = yaml.safe_load(text)
    assert list(parsed["services"]) == ["api", "module-manager", "worker"]
    assert parsed["services"]["api"] == {
        "image": f"ghcr.io/installation-04/cobble-api:1.2.3@sha256:{D}",
        "pull_policy": "always",
    }
    assert "postgres" not in parsed["services"]  # no build: left alone


def test_output_is_deterministic() -> None:
    args = (COMPOSE, "o", "1.2.3", digests("api", "worker", "module-manager"))
    assert mrc.generate(*args) == mrc.generate(*args)


def test_a_built_service_without_digest_fails() -> None:
    with pytest.raises(mrc.ReleaseComposeError, match="worker"):
        mrc.generate(COMPOSE, "o", "1.2.3", digests("api", "module-manager"))


def test_a_digest_for_a_service_that_does_not_build_fails() -> None:
    with pytest.raises(mrc.ReleaseComposeError, match="postgres"):
        mrc.generate(COMPOSE, "o", "1.2.3", digests("api", "worker", "module-manager", "postgres"))


@pytest.mark.parametrize("version", ["1.2", "latest", "1.2.3+x", "v1.2.3 ", ""])
def test_bad_versions_are_refused(version: str) -> None:
    with pytest.raises(mrc.ReleaseComposeError):
        mrc.generate(COMPOSE, "o", version, digests("api", "worker", "module-manager"))


def test_prerelease_versions_are_accepted() -> None:
    text = mrc.generate(COMPOSE, "o", "v0.3.0-rc.1", digests("api", "worker", "module-manager"))
    assert "cobble-api:0.3.0-rc.1@" in text


@pytest.mark.parametrize("item", ["api", "api=sha256:abc", "api=" + D, "A=sha256:" + D])
def test_bad_digest_arguments_are_refused(item: str) -> None:
    with pytest.raises(mrc.ReleaseComposeError):
        mrc.parse_digests([item])


def test_the_real_compose_file(tmp_path: Path) -> None:
    """Every service that builds in core/compose.yml needs a digest; fake-llm is one of them."""
    services = mrc.built_services(yaml.safe_load((REPO / "core/compose.yml").read_text("utf-8")))
    assert set(services) == {"api", "fake-llm", "module-manager", "ui", "worker"}
    out = tmp_path / "compose.release.yml"
    args = ["--compose", str(REPO / "core/compose.yml"), "--owner", "Owner", "--version", "v0.3.0"]
    for name in services:
        args += ["--digest", f"{name}=sha256:{D}"]
    assert mrc.main([*args, "--output", str(out)]) == 0
    assert set(yaml.safe_load(out.read_text("utf-8"))["services"]) == set(services)
    # A missing digest exits 1 and writes nothing.
    broken = tmp_path / "broken.yml"
    assert mrc.main([*args[:-2], "--output", str(broken)]) == 1
    assert not broken.exists()


@pytest.mark.skipif(shutil.which("git") is None, reason="git is required")
def test_bundle_layout_and_checksums(tmp_path: Path) -> None:
    compose = tmp_path / "compose.release.yml"
    compose.write_text("services: {}\n", "utf-8")
    out = tmp_path / "dist"
    cmd = ["bash", str(SCRIPTS / "make_release_bundle.sh"), "v9.9.9", str(compose), str(out)]
    subprocess.run(cmd, check=True, capture_output=True)  # noqa: S603
    first = (out / "cobble.tar.gz").read_bytes()
    assert sorted(p.name for p in out.iterdir()) == [
        "cobble.tar.gz",
        "cobble.tar.gz.sha256",
        "install.sh",
        "install.sh.sha256",
    ]
    for name in ("cobble.tar.gz", "install.sh"):
        digest = hashlib.sha256((out / name).read_bytes()).hexdigest()
        assert (out / f"{name}.sha256").read_text("utf-8") == f"{digest}  {name}\n"
    with tarfile.open(out / "cobble.tar.gz") as tar:
        names = tar.getnames()
    assert {n.split("/")[0] for n in names} == {"cobble-9.9.9"}
    assert "cobble-9.9.9/core/compose.release.yml" in names
    assert "cobble-9.9.9/core/compose.yml" in names
    banned = (
        ".git/",
        "node_modules",
        ".venv",
        "__pycache__",
        "ui/dist",
        "reference-projects/results",
    )
    assert not [n for n in names if any(b in n for b in banned)]
    # Same commit, same bytes.
    subprocess.run(cmd, check=True, capture_output=True)  # noqa: S603
    assert (out / "cobble.tar.gz").read_bytes() == first
