"""The official catalogue: every module is valid, follows the platform rules and is complete."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from cobble_sdk import Manifest, load_manifest, rewrite_compose

CATALOG = Path(__file__).resolve().parents[3] / "catalog"
MODULES = sorted(p.parent for p in CATALOG.glob("*/manifest.yaml"))


def ids(path: Path) -> str:
    return path.name


@pytest.mark.parametrize("directory", MODULES, ids=ids)
def test_the_manifest_is_valid_and_matches_its_directory(directory: Path) -> None:
    manifest = load_manifest(directory / "manifest.yaml")
    assert manifest.id == directory.name


def _absolute_binds(raw: dict[str, Any], directory: Path) -> dict[str, Any]:
    """What `docker compose config` does to `./file:/target` bind mounts."""
    for service in raw.get("services", {}).values():
        service["volumes"] = [
            f"{directory / volume.split(':', 1)[0]}:{volume.split(':', 1)[1]}"
            if isinstance(volume, str) and volume.startswith("./")
            else volume
            for volume in service.get("volumes", [])
        ]
    return raw


def _rewrite(directory: Path, manifest: Manifest) -> dict[str, object]:
    raw = _absolute_binds(
        yaml.safe_load((directory / manifest.compose).read_text("utf-8")), directory
    )
    return rewrite_compose(
        raw, manifest, module_dir=str(directory), bus_network="cobble_core"
    ).compose


@pytest.mark.parametrize("directory", MODULES, ids=ids)
def test_the_compose_file_follows_the_platform_rules(directory: Path) -> None:
    manifest = load_manifest(directory / "manifest.yaml")
    compose = _rewrite(directory, manifest)
    assert compose["name"] == f"cobble-{manifest.id}"


@pytest.mark.parametrize("directory", MODULES, ids=ids)
def test_images_in_the_compose_file_are_the_declared_ones(directory: Path) -> None:
    manifest = load_manifest(directory / "manifest.yaml")
    raw = yaml.safe_load((directory / manifest.compose).read_text("utf-8"))
    used = {service["image"] for service in raw["services"].values() if "image" in service}
    assert used == set(manifest.images)


@pytest.mark.parametrize("directory", MODULES, ids=ids)
def test_every_hook_exists_and_is_executable_bash(directory: Path) -> None:
    manifest = load_manifest(directory / "manifest.yaml")
    hooks = manifest.hooks
    scripts = [hooks.post_install, hooks.register_core, hooks.pre_uninstall]
    scripts += [*hooks.on_link.values(), *hooks.on_unlink.values()]
    for script in filter(None, scripts):
        path = directory / script
        assert path.is_file(), script
        text = path.read_text("utf-8")
        assert text.startswith("#!/usr/bin/env bash\n"), script
        assert "set -euo pipefail" in text, script
        assert path.stat().st_mode & 0o111, f"{script} is not executable"


@pytest.mark.parametrize("directory", MODULES, ids=ids)
def test_a_hook_never_prints_a_secret_it_was_given(directory: Path) -> None:
    """Only `::secret::` lines are read from a hook, and they must never echo an input secret."""
    for script in (directory / "hooks").glob("*.sh") if (directory / "hooks").is_dir() else []:
        for line in script.read_text("utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith(("echo ", "printf ")) and "COBBLE_SECRET_" in stripped:
                assert "::secret::" in stripped, f"{script.name}: {stripped}"


def test_forgejo_provides_git_and_exposes_only_its_token_to_the_core() -> None:
    manifest = load_manifest(CATALOG / "forgejo" / "manifest.yaml")
    assert [p.capability for p in manifest.provides] == ["git"]
    assert manifest.exclusive == ["git"]
    assert manifest.core_secrets == ["api_token"]
    assert "api_token" not in manifest.secrets  # minted by the hook, not generated
    assert manifest.web_ui is not None and manifest.web_ui.path == "/git"


def test_woodpecker_needs_git_and_keeps_its_service_account_secret_out_of_the_core() -> None:
    forgejo = load_manifest(CATALOG / "forgejo" / "manifest.yaml")
    woodpecker = load_manifest(CATALOG / "woodpecker" / "manifest.yaml")
    assert woodpecker.requires == ["git"] and [p.capability for p in woodpecker.provides] == ["ci"]
    # the CI hooks may read the Git server's admin password; the core may not
    assert forgejo.link_secrets == ["admin_password"]
    assert "admin_password" not in forgejo.core_secrets
    assert woodpecker.core_secrets == ["api_token"]
    assert woodpecker.host_access == ["docker_socket"]
    assert woodpecker.web_ui is not None and woodpecker.web_ui.strip_prefix is False


def test_only_woodpecker_mounts_the_docker_socket() -> None:
    for directory in MODULES:
        manifest = load_manifest(directory / "manifest.yaml")
        text = (directory / manifest.compose).read_text("utf-8")
        assert ("docker.sock" in text) == (manifest.id == "woodpecker"), manifest.id
