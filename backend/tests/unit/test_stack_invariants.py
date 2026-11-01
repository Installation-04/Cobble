"""Static checks on the core stack: pinned images, one published port, hardening."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
COMPOSE = yaml.safe_load((ROOT / "core" / "compose.yml").read_text("utf-8"))
SERVICES: dict[str, dict[str, object]] = COMPOSE["services"]
DOCKERFILES = [
    ROOT / "backend" / "Dockerfile",
    ROOT / "providers" / "fake-llm" / "Dockerfile",
    ROOT / "ui" / "Dockerfile",
]


def test_every_compose_image_is_pinned_by_digest() -> None:
    images = [str(s["image"]) for s in SERVICES.values() if "image" in s]
    assert images
    for image in images:
        assert re.search(r"@sha256:[0-9a-f]{64}$", image), f"not pinned by digest: {image}"
        assert ":latest" not in image


@pytest.mark.parametrize("dockerfile", DOCKERFILES, ids=lambda p: p.parent.name)
def test_dockerfile_images_are_pinned_and_run_as_non_root(dockerfile: Path) -> None:
    text = dockerfile.read_text("utf-8")
    stages = set(re.findall(r"^FROM\s+\S+\s+AS\s+(\S+)", text, re.M | re.I))
    # Named build contexts that compose provides from a local directory (not images).
    contexts = {
        name
        for service in SERVICES.values()
        if isinstance(service.get("build"), dict)
        for name in service["build"].get("additional_contexts", {})
    }
    refs = [
        ref
        for ref in re.findall(r"^FROM\s+(\S+)", text, re.M) + re.findall(r"--from=(\S+)", text)
        if ref not in stages and ref not in contexts
    ]
    assert refs
    for ref in refs:
        assert "@sha256:" in ref, f"not pinned by digest: {ref}"
    assert re.search(r"^USER\s+(?!root\b)\S+", text, re.M)


def test_only_caddy_publishes_a_host_port() -> None:
    published = {name for name, s in SERVICES.items() if s.get("ports")}
    assert published == {"caddy"}


def test_core_network_is_internal_and_services_drop_capabilities() -> None:
    assert COMPOSE["networks"]["core"]["internal"] is True
    for name, service in SERVICES.items():
        assert service.get("cap_drop") == ["ALL"], f"{name} must drop all capabilities"
        assert "no-new-privileges:true" in service.get("security_opt", []), name


def test_no_secret_value_is_committed_in_compose() -> None:
    text = (ROOT / "core" / "compose.yml").read_text("utf-8")
    for line in text.splitlines():
        if re.search(r"(PASSWORD|KEY)\s*[:=]", line):
            assert "${" in line or "REDISCLI" in line or "--requirepass" in line, line


# --- the module-manager (rule 5: the only container with the Docker socket and the vault key) ---


def _mounts(service: dict[str, object]) -> list[str]:
    return [str(v) for v in service.get("volumes", [])]  # type: ignore[attr-defined]


def test_only_the_module_manager_gets_the_docker_socket_and_the_vault_key() -> None:
    with_socket = {n for n, s in SERVICES.items() if any("docker.sock" in m for m in _mounts(s))}
    with_key = {
        n for n, s in SERVICES.items() if any("cobble-module-keys" in m for m in _mounts(s))
    }
    assert with_socket == {"module-manager"}
    assert with_key == {"module-manager"}
    for name in ("api", "worker"):
        assert "COBBLE_MODULE_MASTER_KEY_FILE" not in SERVICES[name].get("environment", {})  # type: ignore[operator]


def test_the_module_manager_is_off_by_default_and_has_its_own_image_target() -> None:
    service = SERVICES["module-manager"]
    assert service["profiles"] == ["modules"]
    assert service["build"]["target"] == "module-manager"  # type: ignore[index]
    assert service["read_only"] is True
    assert "ports" not in service
    assert all(SERVICES[n].get("profiles") is None for n in SERVICES if n != "module-manager")


def test_the_default_backend_image_target_stays_the_plain_backend() -> None:
    text = (ROOT / "backend" / "Dockerfile").read_text("utf-8")
    stages = re.findall(r"^FROM\s+\S+\s+AS\s+(\S+)", text, re.M | re.I)
    assert stages[-1] == "backend"  # a build without --target gets the API/worker image
    assert "docker-cli" in stages
    for name in ("api", "worker"):
        assert SERVICES[name]["build"]["target"] == "backend"  # type: ignore[index]
    docker_cli = re.search(r"^FROM\s+(\S+)\s+AS\s+docker-cli", text, re.M)
    assert docker_cli is not None
    assert "@sha256:" in docker_cli.group(1)
    # the Docker CLI is copied into the module-manager stage only
    manager_stage = text.split("AS module-manager", 1)[1].split("AS backend", 1)[0]
    assert "COPY --from=docker-cli" in manager_stage
    assert "docker-cli" not in text.split("AS backend", 1)[1]


def _volume_users(volume: str) -> dict[str, str]:
    """service -> mount string, for every service that mounts the named volume."""
    found: dict[str, str] = {}
    for name, service in SERVICES.items():
        for mount in service.get("volumes", []):  # type: ignore[attr-defined]
            if str(mount).startswith(f"{volume}:"):
                found[name] = str(mount)
    return found


def test_only_the_module_manager_can_write_the_routes_and_only_caddy_reads_them() -> None:
    mounts = _volume_users("cobble-caddy-routes")
    assert set(mounts) == {"module-manager", "caddy", "caddy-init"}
    assert mounts["caddy"].endswith(":ro")
    assert not mounts["module-manager"].endswith(":ro")
    # the one-shot that fixes the owner may only change an owner, once
    init = SERVICES["caddy-init"]
    assert init["restart"] == "no" and init["cap_add"] == ["CHOWN"]
    assert SERVICES["caddy"]["depends_on"]["caddy-init"] == {  # type: ignore[index]
        "condition": "service_completed_successfully"
    }


def test_the_caddy_admin_socket_is_shared_with_the_module_manager_only() -> None:
    assert set(_volume_users("cobble-caddy-run")) == {"caddy", "module-manager"}
    caddyfile = (ROOT / "core" / "caddy" / "Caddyfile").read_text("utf-8")
    assert "admin unix//run/caddy/admin.sock" in caddyfile
    assert re.search(r"^\s*admin\s+(off|:|localhost|\d)", caddyfile, re.M) is None  # no TCP admin
    assert "import /etc/caddy/routes/*.caddy" in caddyfile
