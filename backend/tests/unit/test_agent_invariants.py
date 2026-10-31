"""Static checks on the agent runner side: image, agent-service, proxy and their compose file."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
PACK = ROOT / "packs" / "v01"
COMPOSE_FILE = PACK / "compose.agents.yml"
COMPOSE = yaml.safe_load(COMPOSE_FILE.read_text("utf-8"))
SERVICES: dict[str, dict[str, object]] = COMPOSE["services"]
DOCKERFILES = [
    ROOT / "runners" / "aider" / "Dockerfile",
    PACK / "agent-service" / "Dockerfile",
    PACK / "agent-proxy" / "Dockerfile",
]
SECRET_FILES = [
    COMPOSE_FILE,
    *DOCKERFILES,
    ROOT / "runners" / "aider" / "entrypoint",
    ROOT / "runners" / "aider" / "test-wrapper",
    PACK / "agent-proxy" / "entrypoint.sh",
    PACK / "agent-proxy" / "tinyproxy.conf.tmpl",
    PACK / "agent-service" / "gen-env.sh",
]


def test_images_are_pinned_by_digest_or_built_locally_from_pinned_bases() -> None:
    for name, service in SERVICES.items():
        if "build" in service:
            continue
        image = str(service["image"])
        assert re.search(r"@sha256:[0-9a-f]{64}$", image), f"{name}: not pinned by digest"
        assert ":latest" not in image


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
    text = (ROOT / "runners" / "aider" / "Dockerfile").read_text("utf-8")
    assert re.search(r"^USER\s+10001\s*$", text, re.M)
    code = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
    assert "docker" not in code.lower()


def test_no_agent_side_service_publishes_a_host_port() -> None:
    assert [n for n, s in SERVICES.items() if s.get("ports")] == []


def test_only_agent_service_mounts_the_docker_socket() -> None:
    holders = {
        name
        for name, s in SERVICES.items()
        if any("docker.sock" in str(v) for v in s.get("volumes", []))  # type: ignore[attr-defined]
    }
    assert holders == {"agent-service"}
    # ...and the runner image, its scripts and the proxy never reference it.
    for path in [
        ROOT / "runners" / "aider" / "entrypoint",
        ROOT / "runners" / "aider" / "test-wrapper",
        PACK / "agent-proxy" / "entrypoint.sh",
    ]:
        assert "docker.sock" not in path.read_text("utf-8")


def test_services_are_hardened_and_non_root() -> None:
    for name, service in SERVICES.items():
        if name == "agent-runner-image":  # build-only entry, never started
            assert service["profiles"] == ["build"]
            continue
        assert service.get("cap_drop") == ["ALL"], name
        assert "no-new-privileges:true" in service.get("security_opt", []), name  # type: ignore[operator]
        assert service.get("read_only") is True, name
    assert str(SERVICES["agent-service"]["user"]).split(":")[0] not in {"0", "root"}
    assert SERVICES["agent-service"].get("group_add")  # joins the socket's group instead of root


def test_agents_network_is_internal_and_only_the_proxy_straddles_it() -> None:
    assert COMPOSE["networks"]["agents"]["internal"] is True
    assert COMPOSE["networks"]["core"]["external"] is True
    on_agents = {
        name
        for name, s in SERVICES.items()
        if "agents" in (s.get("networks") or [])  # type: ignore[operator]
    }
    assert on_agents == {"agent-proxy"}  # agent containers are attached by agent-service itself


def test_proxy_default_allow_list_is_minimal() -> None:
    env = SERVICES["agent-proxy"]["environment"]
    default = re.search(r":-([^}]+)\}", str(env["AGENT_PROXY_ALLOW"]))  # type: ignore[index]
    assert default
    assert set(default.group(1).split(",")) == {
        "api",
        "pypi.org",
        "files.pythonhosted.org",
        "registry.npmjs.org",
    }
    conf = (PACK / "agent-proxy" / "tinyproxy.conf.tmpl").read_text("utf-8")
    assert re.search(r"^FilterDefaultDeny\s+Yes", conf, re.M)
    assert re.search(r"^ConnectPort\s+443\s*$", conf, re.M)


@pytest.mark.parametrize("path", SECRET_FILES, ids=lambda p: p.name)
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


def test_agent_env_files_are_private_and_ignored_by_git() -> None:
    script = (PACK / "agent-service" / "gen-env.sh").read_text("utf-8")
    assert "umask 077" in script and "chmod 600" in script
    ignore = (PACK / ".gitignore").read_text("utf-8")
    assert ".env.*" in ignore


@pytest.mark.parametrize("service", ["agent-service", "preview-service"])
def test_gen_env_works_on_a_first_run(service: str, tmp_path: Path) -> None:
    """With no previous output file the generator must still succeed (pipefail regression)."""
    import os
    import subprocess

    pack_env = tmp_path / "pack.env"
    pack_env.write_text("COBBLE_PACK_FORGEJO_URL=http://forgejo:3000\n", "utf-8")
    env = {
        **os.environ,
        "COBBLE_PACK_CORE_ENV": str(pack_env),
        "COBBLE_AGENT_ENV": str(tmp_path / "agents.env"),
        "COBBLE_AGENT_CORE_ENV": str(tmp_path / "agents.core.env"),
        "COBBLE_PREVIEW_ENV": str(tmp_path / "preview.env"),
        "COBBLE_PREVIEW_CORE_ENV": str(tmp_path / "preview.core.env"),
    }
    result = subprocess.run(  # noqa: S603
        ["bash", str(PACK / service / "gen-env.sh")],  # noqa: S607
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_backend_image_ships_git() -> None:
    """The Forgejo provider shells out to git (found missing on the first full-chain run)."""
    assert re.search(
        r"apt-get install[^\n]*\bgit\b", (ROOT / "backend" / "Dockerfile").read_text("utf-8")
    )


def test_runner_image_prewarms_the_template_dependencies() -> None:
    dockerfile = (ROOT / "runners" / "aider" / "Dockerfile").read_text("utf-8")
    assert "FROM scratch AS template" in dockerfile and "/opt/uv-seed" in dockerfile
    compose = (PACK / "compose.agents.yml").read_text("utf-8")
    assert "additional_contexts" in compose and "templates/fastapi-react" in compose
    assert "/opt/uv-seed" in (ROOT / "runners" / "aider" / "entrypoint").read_text("utf-8")


def test_runner_image_does_not_leak_aiders_uv_environment() -> None:
    """A global UV_PROJECT_ENVIRONMENT sent the project's `uv run` into Aider's read-only venv."""
    dockerfile = (ROOT / "runners" / "aider" / "Dockerfile").read_text("utf-8")
    env_blocks = re.findall(r"^ENV\s[^\n]*(?:\\\n[^\n]*)*", dockerfile, re.M)
    assert not any("UV_PROJECT_ENVIRONMENT" in block for block in env_blocks)
