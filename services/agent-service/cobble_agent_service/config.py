"""Service settings, read from the environment (see docs/en/agents.md)."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path


class ConfigError(RuntimeError):
    """A required setting is missing or invalid."""


@dataclass(frozen=True)
class Settings:
    """All settings of agent-service. Secrets are never logged (see `__repr__` users)."""

    token: str
    data_dir: Path
    runner_image: str
    api_url: str
    forgejo_url: str
    forgejo_token: str
    forgejo_user: str = "cobble-bot"
    # Exactly one of data_volume (named Docker volume mounted at data_dir) or data_host_dir
    # (host directory mounted at the same path) tells the daemon where data_dir lives.
    data_volume: str = ""
    data_host_dir: str = ""
    docker_socket: str = "/var/run/docker.sock"
    network: str = "cobble_agents"
    proxy_url: str = "http://agent-proxy:3128"
    no_proxy: str = "localhost,127.0.0.1"
    git_rewrite_from: str = ""
    git_rewrite_to: str = ""
    loop_threshold: int = 8
    max_runs: int = 8
    retention_hours: float = 24.0
    cap_cpu: float = 4.0
    cap_memory_mb: int = 8192
    cap_pids: int = 1024
    cap_seconds: int = 3600
    tmp_mb: int = 1024
    log_limit_bytes: int = 50 * 1024 * 1024
    agent_cmd: str = ""  # test hook only: forwarded as COBBLE_AGENT_CMD to the runner

    def __repr__(self) -> str:  # pragma: no cover - guards against accidental secret logging
        return "Settings(...)"

    @property
    def runs_dir(self) -> Path:
        return self.data_dir / "runs"

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        e = os.environ if env is None else env

        def need(name: str) -> str:
            value = e.get(name, "").strip()
            if not value:
                raise ConfigError(f"{name} is required")
            return value

        rewrite = e.get("COBBLE_AGENT_GIT_REWRITE", "").strip()
        rewrite_from, rewrite_to = "", ""
        if rewrite:
            if "=" not in rewrite:
                raise ConfigError("COBBLE_AGENT_GIT_REWRITE must look like 'from-prefix=to-prefix'")
            rewrite_from, rewrite_to = rewrite.split("=", 1)
        volume = e.get("COBBLE_AGENT_DATA_VOLUME", "").strip()
        host_dir = e.get("COBBLE_AGENT_DATA_HOST_DIR", "").strip()
        if bool(volume) == bool(host_dir):
            raise ConfigError(
                "set exactly one of COBBLE_AGENT_DATA_VOLUME, COBBLE_AGENT_DATA_HOST_DIR"
            )
        return cls(
            token=need("COBBLE_AGENT_SERVICE_TOKEN"),
            data_dir=Path(e.get("COBBLE_AGENT_DATA_DIR", "/data")),
            runner_image=need("COBBLE_AGENT_RUNNER_IMAGE"),
            api_url=need("COBBLE_INTERNAL_API_URL").rstrip("/"),
            forgejo_url=need("COBBLE_PACK_FORGEJO_URL").rstrip("/"),
            forgejo_token=need("COBBLE_PACK_FORGEJO_TOKEN"),
            forgejo_user=e.get("COBBLE_PACK_FORGEJO_OWNER", "cobble-bot") or "cobble-bot",
            data_volume=volume,
            data_host_dir=host_dir,
            docker_socket=e.get("COBBLE_AGENT_DOCKER_SOCKET", "/var/run/docker.sock"),
            network=e.get("COBBLE_AGENT_NETWORK", "cobble_agents"),
            proxy_url=e.get("COBBLE_AGENT_PROXY_URL", "http://agent-proxy:3128"),
            no_proxy=e.get("COBBLE_AGENT_NO_PROXY", "localhost,127.0.0.1"),
            git_rewrite_from=rewrite_from,
            git_rewrite_to=rewrite_to,
            loop_threshold=int(e.get("COBBLE_LOOP_THRESHOLD", "8")),
            max_runs=int(e.get("COBBLE_AGENT_MAX_RUNS", "8")),
            retention_hours=float(e.get("COBBLE_AGENT_RETENTION_HOURS", "24")),
            cap_cpu=float(e.get("COBBLE_AGENT_MAX_CPU", "4")),
            cap_memory_mb=int(e.get("COBBLE_AGENT_MAX_MEMORY_MB", "8192")),
            cap_pids=int(e.get("COBBLE_AGENT_MAX_PIDS", "1024")),
            cap_seconds=int(e.get("COBBLE_AGENT_MAX_SECONDS", "3600")),
            tmp_mb=int(e.get("COBBLE_AGENT_TMP_MB", "1024")),
            agent_cmd=e.get("COBBLE_AGENT_CMD", ""),
        )
