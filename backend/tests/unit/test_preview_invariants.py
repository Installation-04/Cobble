"""Static checks on the demo side of the pack: preview-service, its compose file, the Caddy
snippet and the template Dockerfile it builds (ADR 0007)."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]
PACK = ROOT / "packs" / "v01"
SERVICE = PACK / "preview-service"
COMPOSE_FILE = PACK / "compose.preview.yml"
COMPOSE = yaml.safe_load(COMPOSE_FILE.read_text("utf-8"))
SERVICES: dict[str, dict[str, object]] = COMPOSE["services"]
DOCKERFILES = [SERVICE / "Dockerfile", ROOT / "templates" / "fastapi-react" / "Dockerfile"]
DIGEST = re.compile(r"@sha256:[0-9a-f]{64}$")


def test_images_are_pinned_by_digest_or_built_locally() -> None:
    for name, service in SERVICES.items():
        if "build" in service:
            continue
        assert DIGEST.search(str(service["image"])), f"{name}: not pinned by digest"


def test_dockerfiles_pin_their_bases_and_run_as_non_root() -> None:
    for dockerfile in DOCKERFILES:
        text = dockerfile.read_text("utf-8")
        stages = set(re.findall(r"^FROM\s+\S+\s+AS\s+(\S+)", text, re.M | re.I))
        refs = [
            ref
            for ref in re.findall(r"^FROM\s+(\S+)", text, re.M) + re.findall(r"--from=(\S+)", text)
            if ref not in stages
        ]
        assert refs, dockerfile
        for ref in refs:
            assert "@sha256:" in ref, f"{dockerfile.parent.name}: not pinned by digest: {ref}"
        users = re.findall(r"^USER\s+(\S+)", text, re.M)
        assert users and users[-1] not in {"root", "0"}, dockerfile


def test_no_host_port_is_published() -> None:
    assert [n for n, s in SERVICES.items() if s.get("ports")] == []


def test_only_preview_service_mounts_the_docker_socket() -> None:
    holders = {
        name
        for name, s in SERVICES.items()
        if any("docker.sock" in str(v) for v in s.get("volumes", []))  # type: ignore[attr-defined]
    }
    assert holders == {"preview-service"}
    # The demo caddy snippet and the template never reference it.
    assert "docker.sock" not in (SERVICE / "demo.caddy").read_text("utf-8")
    assert "docker.sock" not in (ROOT / "templates" / "fastapi-react" / "Dockerfile").read_text(
        "utf-8"
    )


def test_service_is_hardened_and_non_root() -> None:
    for name, service in SERVICES.items():
        assert service.get("cap_drop") == ["ALL"], name
        assert "no-new-privileges:true" in service.get("security_opt", []), name  # type: ignore[operator]
        assert service.get("read_only") is True, name
        assert service.get("mem_limit") and service.get("pids_limit"), name
    assert str(SERVICES["preview-service"]["user"]).split(":")[0] not in {"0", "root"}


def test_demos_live_on_an_internal_network() -> None:
    assert COMPOSE["networks"]["previews"]["internal"] is True
    assert COMPOSE["networks"]["core"]["external"] is True
    assert SERVICES["preview-service"]["networks"] == ["core", "previews"]


def test_demo_containers_are_created_confined() -> None:
    text = (SERVICE / "cobble_preview_service" / "manager.py").read_text("utf-8")
    for needle in (
        '"ReadonlyRootfs": True',
        '"CapDrop": ["ALL"]',
        '"no-new-privileges:true"',
        '"Privileged": False',
        "PidsLimit",
        "NanoCpus",
        '"User": NON_ROOT',
    ):
        assert needle in text, needle
    for forbidden in ("PortBindings", "docker.sock", "Binds", "Mounts", "HostNetwork"):
        assert forbidden not in text, forbidden


def test_caddy_snippet_lives_outside_the_always_imported_directory() -> None:
    assert (SERVICE / "demo.caddy").is_file()
    assert not list((PACK / "caddy").glob("demo*.caddy"))  # the installer copies it on demand
    snippet = (SERVICE / "demo.caddy").read_text("utf-8")
    assert re.search(r"^handle /demo/\*\s*\{", snippet, re.M)
    assert "reverse_proxy preview-service:8091" in snippet


def test_no_secret_value_is_committed() -> None:
    paths = [COMPOSE_FILE, *DOCKERFILES, SERVICE / "gen-env.sh", SERVICE / "demo.caddy"]
    for path in paths:
        for line in path.read_text("utf-8").splitlines():
            if line.lstrip().startswith("#"):
                continue
            match = re.search(r"\b[A-Z_]*(PASSWORD|SECRET|TOKEN|API_KEY)\s*[:=]\s*(\S+)", line)
            if match:
                value = match.group(2).strip("\"'")
                assert value == "" or value.startswith(("$", "<")) or "$(" in value, (
                    f"{path.name}: {line.strip()}"
                )


def test_env_files_are_private() -> None:
    script = (SERVICE / "gen-env.sh").read_text("utf-8")
    assert "umask 077" in script and "chmod 600" in script
    assert ".env.*" in (PACK / ".gitignore").read_text("utf-8")
