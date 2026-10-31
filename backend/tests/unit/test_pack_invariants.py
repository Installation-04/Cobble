"""Static checks on the v0.1 pack: pinned images, no published port, Docker socket confined to
the CI agent, no secret literal, hooks and template pipeline pinned too."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]
PACK = ROOT / "packs" / "v01"
COMPOSE = yaml.safe_load((PACK / "compose.yml").read_text("utf-8"))
SERVICES: dict[str, dict[str, object]] = COMPOSE["services"]
DIGEST = re.compile(r"@sha256:[0-9a-f]{64}$")


def test_every_pack_image_is_pinned_by_digest() -> None:
    images = [str(s["image"]) for s in SERVICES.values()]
    assert len(images) == len(SERVICES)  # no build: only pinned images
    for image in images:
        assert DIGEST.search(image), f"not pinned by digest: {image}"
        assert ":latest" not in image


def test_pack_publishes_no_host_port() -> None:
    assert [name for name, s in SERVICES.items() if s.get("ports")] == []


def test_only_the_ci_agent_mounts_the_docker_socket() -> None:
    mounting = {
        name
        for name, s in SERVICES.items()
        if any("docker.sock" in str(v) for v in s.get("volumes", []))  # type: ignore[attr-defined]
    }
    assert mounting == {"woodpecker-agent"}


def test_services_drop_capabilities_and_forbid_privilege_gain() -> None:
    for name, service in SERVICES.items():
        assert service.get("cap_drop") == ["ALL"], name
        assert "no-new-privileges:true" in service.get("security_opt", []), name  # type: ignore[operator]
        assert not service.get("privileged"), name
        assert service.get("mem_limit"), f"{name} needs a memory limit"


def test_pack_services_do_not_run_as_root_except_documented_init() -> None:
    for name in ("woodpecker-server", "woodpecker-agent"):
        user = str(SERVICES[name]["user"])
        assert not user.startswith(("0", "root")), name


def test_networks_are_namespaced_and_the_core_one_is_external() -> None:
    nets = COMPOSE["networks"]
    assert nets["core"] == {"name": "cobble_core", "external": True}
    assert nets["pack"]["internal"] is True
    for key in ("pack", "ci"):
        assert nets[key]["name"].startswith("cobble-pack-")
    assert COMPOSE["name"] == "cobble-pack"
    for volume in COMPOSE["volumes"]:
        assert volume.startswith("cobble-pack-")


def test_no_secret_value_is_committed_in_compose() -> None:
    text = (PACK / "compose.yml").read_text("utf-8")
    for line in text.splitlines():
        if not line.lstrip().startswith("#") and re.search(
            r"(SECRET|TOKEN|PASSWORD|KEY|CLIENT)\w*\s*:", line
        ):
            assert "${" in line, f"secret literal? {line.strip()}"


def test_generated_secret_files_are_git_ignored() -> None:
    ignore = (PACK / ".gitignore").read_text("utf-8")
    assert ".env" in ignore and ".env.*" in ignore


def test_hooks_pin_the_images_they_run() -> None:
    text = "\n".join(p.read_text("utf-8") for p in (PACK / "hooks").glob("*.sh"))
    for image in re.findall(r'(?:IMAGE|image)="?([\w./-]+:[\w.-]+(?:@sha256:\w+)?)"?', text):
        assert DIGEST.search(image), image


def test_template_pipeline_images_are_pinned_and_scanners_present() -> None:
    pipeline = yaml.safe_load(
        (ROOT / "templates" / "fastapi-react" / ".woodpecker.yaml").read_text("utf-8")
    )
    names = {step["name"] for step in pipeline["steps"]}
    assert {"lint", "backend-tests", "frontend-tests", "semgrep", "trivy", "gitleaks"} <= names
    for step in pipeline["steps"]:
        assert DIGEST.search(step["image"]), step["image"]


def test_caddy_snippet_routes_both_products_under_subpaths() -> None:
    text = (PACK / "caddy" / "pack.caddy").read_text("utf-8")
    assert "handle_path /git/*" in text and "forgejo:3000" in text
    assert "handle /ci/*" in text and "woodpecker-server:8000" in text
