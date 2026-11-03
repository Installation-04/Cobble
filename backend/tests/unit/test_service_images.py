"""Static checks on the images the agent and preview modules ship, and on their compose files.

The compose files are the catalogue's (`catalog/aider`, `catalog/preview`); the images are built
from `services/` and `runners/` by the "Module images" workflow and pinned by digest in them.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
SERVICE_DIRS = ROOT / "services"
RUNNER = ROOT / "runners" / "aider"
CATALOG = ROOT / "catalog"
DOCKERFILES = [
    RUNNER / "Dockerfile",
    SERVICE_DIRS / "agent-service" / "Dockerfile",
    SERVICE_DIRS / "agent-proxy" / "Dockerfile",
    SERVICE_DIRS / "preview-service" / "Dockerfile",
    ROOT / "templates" / "fastapi-react" / "Dockerfile",
]


def compose(module: str) -> dict[str, Any]:
    loaded = yaml.safe_load((CATALOG / module / "compose.yml").read_text("utf-8"))
    assert isinstance(loaded, dict)
    return loaded


@pytest.mark.parametrize("dockerfile", DOCKERFILES, ids=lambda p: p.parent.name)
def test_dockerfiles_pin_bases_and_run_as_non_root(dockerfile: Path) -> None:
    text = dockerfile.read_text("utf-8")
    stages = set(re.findall(r"^FROM\s+\S+\s+AS\s+(\S+)", text, re.M | re.I))
    refs = [
        ref
        for ref in re.findall(r"^FROM\s+(\S+)", text, re.M) + re.findall(r"--from=(\S+)", text)
        if ref not in stages and ref != "scratch"  # scratch: the empty image, nothing to pin
    ]
    assert refs
    for ref in refs:
        assert "@sha256:" in ref, f"not pinned by digest: {ref}"
    users = re.findall(r"^USER\s+(\S+)", text, re.M)
    assert users and users[-1] not in {"root", "0"}


def test_runner_image_runs_as_uid_10001_without_docker() -> None:
    text = (RUNNER / "Dockerfile").read_text("utf-8")
    assert re.search(r"^USER\s+10001\s*$", text, re.M)
    code = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
    assert "docker" not in code.lower()


def test_the_runner_and_the_proxy_never_reference_the_docker_socket() -> None:
    for path in (
        RUNNER / "entrypoint",
        RUNNER / "test-wrapper",
        SERVICE_DIRS / "agent-proxy" / "entrypoint.sh",
    ):
        assert "docker.sock" not in path.read_text("utf-8")
    assert "docker.sock" not in (ROOT / "templates" / "fastapi-react" / "Dockerfile").read_text(
        "utf-8"
    )


@pytest.mark.parametrize("module", ["aider", "preview"])
def test_module_services_are_hardened_and_publish_no_port(module: str) -> None:
    services: dict[str, dict[str, Any]] = compose(module)["services"]
    for name, service in services.items():
        assert service.get("cap_drop") == ["ALL"], name
        assert "no-new-privileges:true" in service.get("security_opt", []), name
        assert service.get("read_only") is True, name
        assert service.get("mem_limit") and service.get("pids_limit"), name
        assert not service.get("ports"), name


@pytest.mark.parametrize(
    ("module", "holder"), [("aider", "agent-service"), ("preview", "preview-service")]
)
def test_only_the_service_that_starts_containers_mounts_the_docker_socket(
    module: str, holder: str
) -> None:
    services: dict[str, dict[str, Any]] = compose(module)["services"]
    holders = {
        n for n, s in services.items() if any("docker.sock" in str(v) for v in s.get("volumes", []))
    }
    assert holders == {holder}
    user = str(services[holder]["user"]).split(":")[0]
    assert user not in {"0", "root"}
    assert services[holder].get("group_add")  # joins the socket's group instead of being root


def test_the_agents_network_is_internal_and_only_the_proxy_is_attached_by_the_module() -> None:
    document = compose("aider")
    assert document["networks"]["agents"]["internal"] is True
    on_agents = {
        n for n, s in document["services"].items() if "agents" in (s.get("networks") or [])
    }
    assert on_agents == {"agent-proxy"}  # agent containers are attached by agent-service itself


def test_the_demo_network_is_internal() -> None:
    document = compose("preview")
    assert document["networks"]["previews"]["internal"] is True
    assert document["services"]["preview-service"]["networks"] == ["previews"]


def test_proxy_default_allow_list_is_minimal() -> None:
    env = compose("aider")["services"]["agent-proxy"]["environment"]
    default = re.search(r":-([^}]+)\}", str(env["AGENT_PROXY_ALLOW"]))
    assert default
    assert set(default.group(1).split(",")) == {
        "api",
        "pypi.org",
        "files.pythonhosted.org",
        "registry.npmjs.org",
    }
    conf = (SERVICE_DIRS / "agent-proxy" / "tinyproxy.conf.tmpl").read_text("utf-8")
    assert re.search(r"^FilterDefaultDeny\s+Yes", conf, re.M)
    assert re.search(r"^ConnectPort\s+443\s*$", conf, re.M)


FILES_WITHOUT_SECRETS = [
    *DOCKERFILES,
    CATALOG / "aider" / "compose.yml",
    CATALOG / "preview" / "compose.yml",
    RUNNER / "entrypoint",
    RUNNER / "test-wrapper",
    SERVICE_DIRS / "agent-proxy" / "entrypoint.sh",
    SERVICE_DIRS / "agent-proxy" / "tinyproxy.conf.tmpl",
]


@pytest.mark.parametrize("path", FILES_WITHOUT_SECRETS, ids=lambda p: f"{p.parent.name}/{p.name}")
def test_no_secret_value_is_committed(path: Path) -> None:
    for line in path.read_text("utf-8").splitlines():
        if line.lstrip().startswith("#"):
            continue
        match = re.search(r"\b[A-Z_]*(PASSWORD|SECRET|TOKEN|API_KEY)\s*[:=]\s*(\S+)", line)
        if match:
            value = match.group(2).strip("\"'")
            assert (
                value == ""
                or value.startswith(("$", "<"))
                or "$(" in value
                or value in {"required", "false", "true"}
            ), f"{path.name}: {line.strip()}"


def test_demo_containers_are_created_confined() -> None:
    text = (SERVICE_DIRS / "preview-service" / "cobble_preview_service" / "manager.py").read_text(
        "utf-8"
    )
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


def test_backend_image_ships_git() -> None:
    """The Forgejo provider shells out to git (found missing on the first full-chain run)."""
    assert re.search(
        r"apt-get install[^\n]*\bgit\b", (ROOT / "backend" / "Dockerfile").read_text("utf-8")
    )


def test_runner_image_prewarms_the_template_dependencies() -> None:
    dockerfile = (RUNNER / "Dockerfile").read_text("utf-8")
    assert "FROM scratch AS template" in dockerfile and "/opt/uv-seed" in dockerfile
    workflow = (ROOT / ".github" / "workflows" / "images.yml").read_text("utf-8")
    assert "template=templates/fastapi-react" in workflow  # the published image is built with it
    assert "/opt/uv-seed" in (RUNNER / "entrypoint").read_text("utf-8")


def test_runner_image_does_not_leak_aiders_uv_environment() -> None:
    """A global UV_PROJECT_ENVIRONMENT sent the project's `uv run` into Aider's read-only venv."""
    dockerfile = (RUNNER / "Dockerfile").read_text("utf-8")
    env_blocks = re.findall(r"^ENV\s[^\n]*(?:\\\n[^\n]*)*", dockerfile, re.M)
    assert not any("UV_PROJECT_ENVIRONMENT" in block for block in env_blocks)


def test_runner_image_prewarms_the_pnpm_store() -> None:
    dockerfile = (RUNNER / "Dockerfile").read_text("utf-8")
    assert "pnpm fetch" in dockerfile and "/opt/pnpm-seed" in dockerfile
    assert "/opt/pnpm-seed" in (RUNNER / "entrypoint").read_text("utf-8")
