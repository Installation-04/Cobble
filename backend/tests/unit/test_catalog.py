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


def compose_files(manifest: Manifest) -> list[str]:
    """The module's compose file and the ones its flavours bring."""
    return [manifest.compose, *sorted({v.compose for v in manifest.variants if v.compose})]


def _rewrite(directory: Path, manifest: Manifest, file: str | None = None) -> dict[str, object]:
    raw = _absolute_binds(
        yaml.safe_load((directory / (file or manifest.compose)).read_text("utf-8")), directory
    )
    return rewrite_compose(
        raw, manifest, module_dir=str(directory), bus_network="cobble_core"
    ).compose


@pytest.mark.parametrize("directory", MODULES, ids=ids)
def test_the_compose_file_follows_the_platform_rules(directory: Path) -> None:
    manifest = load_manifest(directory / "manifest.yaml")
    for file in compose_files(manifest):
        compose = _rewrite(directory, manifest, file)
        assert compose["name"] == f"cobble-{manifest.id}", file


@pytest.mark.parametrize("directory", MODULES, ids=ids)
def test_images_in_the_compose_file_are_the_declared_ones(directory: Path) -> None:
    manifest = load_manifest(directory / "manifest.yaml")
    used: set[str] = set()
    text = ""
    for file in compose_files(manifest):
        text += (directory / file).read_text("utf-8")
        raw = yaml.safe_load((directory / file).read_text("utf-8"))
        used |= {service["image"] for service in raw["services"].values() if "image" in service}
    assert used <= set(manifest.images)
    # an image that is not a service (the agents' runner) must still be named in the compose file
    # (where the service reads it) so that a single pin is the one a hook pulls
    assert all(image in text for image in manifest.images)


@pytest.mark.parametrize("directory", MODULES, ids=ids)
def test_every_hook_exists_and_is_executable_bash(directory: Path) -> None:
    manifest = load_manifest(directory / "manifest.yaml")
    hooks = manifest.hooks
    scripts = [hooks.pre_up, hooks.post_install, hooks.register_core, hooks.pre_uninstall]
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
    assert "admin_password" in forgejo.link_secrets and "admin_password" not in forgejo.core_secrets
    assert woodpecker.core_secrets == ["api_token"]
    assert woodpecker.host_access == ["docker_socket"]
    assert woodpecker.web_ui is not None and woodpecker.web_ui.strip_prefix is False


SOCKET_HOLDERS = {"woodpecker", "aider", "preview"}  # each declares it as host_access


def test_only_the_declared_modules_mount_the_docker_socket() -> None:
    for directory in MODULES:
        manifest = load_manifest(directory / "manifest.yaml")
        text = (directory / manifest.compose).read_text("utf-8")
        holder = manifest.id in SOCKET_HOLDERS
        assert ("docker.sock" in text) == holder, manifest.id
        assert (manifest.host_access == ["docker_socket"]) == holder, manifest.id


def test_agents_and_previews_get_git_from_the_peer_and_keep_their_own_token_private() -> None:
    forgejo = load_manifest(CATALOG / "forgejo" / "manifest.yaml")
    assert "api_token" in forgejo.link_secrets  # handed to the hooks of modules that require git
    for module_id, capability, path in (
        ("aider", "agent-runner", "/agents"),
        ("preview", "preview", "/demo"),
    ):
        manifest = load_manifest(CATALOG / module_id / "manifest.yaml")
        assert manifest.requires == ["git"] and [p.capability for p in manifest.provides] == [
            capability
        ]
        assert manifest.secrets == ["service_token"] and manifest.core_secrets == ["service_token"]
        assert manifest.web_ui is not None and manifest.web_ui.path == path
        # the Git address and token are produced by the pre_up hook, never declared or exposed
        assert manifest.hooks.pre_up == "hooks/pre-up.sh"
        hook = (CATALOG / module_id / "hooks" / "pre-up.sh").read_text("utf-8")
        assert "::secret::forgejo_token=" in hook and "::secret::forgejo_url=" in hook
    # only the preview service has a page of its own; the agent service is for the core alone
    assert load_manifest(CATALOG / "aider" / "manifest.yaml").web_ui.public is False  # type: ignore[union-attr]
    assert load_manifest(CATALOG / "preview" / "manifest.yaml").web_ui.public is True  # type: ignore[union-attr]


def test_the_runner_image_is_pinned_and_listed_so_that_the_hook_can_pull_it() -> None:
    manifest = load_manifest(CATALOG / "aider" / "manifest.yaml")
    compose = (CATALOG / "aider" / "compose.yml").read_text("utf-8")
    runner = next(i for i in manifest.images if "cobble-aider-runner" in i)
    assert f"COBBLE_AGENT_RUNNER_IMAGE: {runner}" in compose
    assert "docker pull" in (CATALOG / "aider" / "hooks" / "pre-up.sh").read_text("utf-8")


def test_the_networks_the_agent_and_preview_services_use_are_the_ones_the_platform_creates() -> (
    None
):
    # The services get the names of the (renamed) network and volume through the environment.
    aider = (CATALOG / "aider" / "compose.yml").read_text("utf-8")
    assert "COBBLE_AGENT_NETWORK: cobble-aider-agents" in aider
    assert "COBBLE_AGENT_DATA_VOLUME: cobble-aider-agents-data" in aider
    preview = (CATALOG / "preview" / "compose.yml").read_text("utf-8")
    assert "COBBLE_PREVIEW_NETWORK: cobble-preview-previews" in preview
    for text in (aider, preview):
        assert "internal: true" in text  # sandboxes have no route out of their network


def test_published_images_have_a_real_digest() -> None:
    for directory in MODULES:
        manifest = load_manifest(directory / "manifest.yaml")
        for image in manifest.images:
            assert "@sha256:" + "0" * 64 not in image, f"{manifest.id}: {image} is not pinned yet"


def test_ollama_serves_models_through_the_gateway_with_a_flavour_per_kind_of_hardware() -> None:
    manifest = load_manifest(CATALOG / "ollama" / "manifest.yaml")
    assert [p.capability for p in manifest.provides] == ["llm-backend"]
    assert {v.id for v in manifest.variants} == {"cpu", "nvidia", "amd"}
    # a small model on the CPU, a larger one when a GPU is there
    assert [m.pull for m in manifest.llm_models("cpu")] == ["qwen2.5-coder:1.5b"]
    assert [m.pull for m in manifest.llm_models("nvidia")] == ["qwen2.5-coder:7b"]
    assert manifest.llm_models("amd") == manifest.llm_models("nvidia")
    assert manifest.llm is not None and manifest.llm.service == "ollama"
    # only the flavours that need a GPU declare one, and each brings its own compose file
    gpus = {v.id: v.gpu for v in manifest.variants}
    assert gpus == {"cpu": "none", "nvidia": "nvidia", "amd": "amd"}
    assert {v.id: v.compose for v in manifest.variants} == {
        "cpu": None,
        "nvidia": "compose.nvidia.yml",
        "amd": "compose.amd.yml",
    }


# --- starter packs ------------------------------------------------------------------------------


def _manifests() -> dict[str, Manifest]:
    return {p.name: load_manifest(p / "manifest.yaml") for p in MODULES}


def test_every_starter_pack_is_valid_and_installs_with_nothing_left_to_choose() -> None:
    from cobble_sdk import check_pack, load_packs

    packs, problems = load_packs(CATALOG / "packs")
    assert problems == {}
    assert set(packs) == {"local-gpu", "local-cpu", "api-only"}
    for pack in packs.values():
        assert check_pack(pack, _manifests()) == [], pack.id
        assert pack.name.en and pack.name.fr and pack.description.en and pack.description.fr


@pytest.mark.parametrize(
    ("ram_mb", "gpu", "expected"),
    [
        (32768, "nvidia", "local-gpu"),
        (16384, "amd", "local-gpu"),
        (16384, "none", "local-cpu"),
        (8192, "none", "local-cpu"),
        (6144, "none", "api-only"),
        (4096, "none", "api-only"),
        (2048, "none", None),
    ],
)
def test_the_pack_proposed_for_a_machine_follows_what_it_has(
    ram_mb: int, gpu: str, expected: str | None
) -> None:
    from cobble_sdk import Hardware, load_packs, recommend

    packs, _ = load_packs(CATALOG / "packs")
    assert recommend(packs, _manifests(), Hardware(ram_mb=ram_mb, gpu=gpu)) == expected  # type: ignore[arg-type]


def test_the_local_packs_use_the_flavour_of_ollama_that_matches_the_machine() -> None:
    from cobble_sdk import Hardware, choose_variant

    ollama = _manifests()["ollama"]
    assert choose_variant(ollama, Hardware(ram_mb=16384, gpu="nvidia")).id == "nvidia"  # type: ignore[union-attr]
    assert choose_variant(ollama, Hardware(ram_mb=16384, gpu="amd")).id == "amd"  # type: ignore[union-attr]
    assert choose_variant(ollama, Hardware(ram_mb=16384, gpu="none")).id == "cpu"  # type: ignore[union-attr]
