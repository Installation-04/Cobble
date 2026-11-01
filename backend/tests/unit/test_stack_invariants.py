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
