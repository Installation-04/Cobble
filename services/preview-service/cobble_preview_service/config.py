"""Service settings, read from the environment (see docs/en/demo.md)."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path


class ConfigError(RuntimeError):
    """A required setting is missing or invalid."""


def _flag(value: str, default: bool) -> bool:
    value = value.strip().lower()
    if not value:
        return default
    return value in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    """All settings of preview-service. The tokens are never logged."""

    token: str
    forgejo_url: str
    forgejo_token: str
    forgejo_user: str = "cobble-bot"
    data_dir: Path = Path("/data")
    docker_socket: str = "/var/run/docker.sock"
    # Private network the demo containers live on. Make it `internal` in production: a demo
    # then has no route to the internet or the host, only to this service.
    network: str = "cobble_previews"
    container_port: int = 8000
    memory_mb: int = 512
    cpus: float = 1.0
    pids: int = 256
    tmp_mb: int = 64
    idle_ttl_s: float = 1800.0
    reap_interval_s: float = 30.0
    max_running: int = 6
    build_timeout_s: float = 900.0
    ready_timeout_s: float = 60.0
    max_context_mb: int = 100
    git_rewrite_from: str = ""
    git_rewrite_to: str = ""
    # Sandbox the demos (CSP `sandbox`, no cookies, CORS answered here): see docs/en/demo.md.
    sandbox: bool = True
    build_args: Mapping[str, str] = field(default_factory=dict)

    def __repr__(self) -> str:  # pragma: no cover - guards against accidental secret logging
        return "Settings(...)"

    @property
    def builds_dir(self) -> Path:
        return self.data_dir / "builds"

    @property
    def state_file(self) -> Path:
        return self.data_dir / "previews.json"

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        e = os.environ if env is None else env

        def need(name: str) -> str:
            value = e.get(name, "").strip()
            if not value:
                raise ConfigError(f"{name} is required")
            return value

        rewrite = e.get("COBBLE_PREVIEW_GIT_REWRITE", "").strip()
        rewrite_from, rewrite_to = "", ""
        if rewrite:
            if "=" not in rewrite:
                raise ConfigError("COBBLE_PREVIEW_GIT_REWRITE must look like 'from=to'")
            rewrite_from, rewrite_to = rewrite.split("=", 1)
        build_args: dict[str, str] = {}
        raw = e.get("COBBLE_PREVIEW_BUILD_ARGS", "").strip()
        if raw:
            try:
                parsed = json.loads(raw)
            except ValueError:
                raise ConfigError("COBBLE_PREVIEW_BUILD_ARGS must be a JSON object") from None
            if not isinstance(parsed, dict):
                raise ConfigError("COBBLE_PREVIEW_BUILD_ARGS must be a JSON object")
            build_args = {str(k): str(v) for k, v in parsed.items()}
        return cls(
            token=need("COBBLE_PREVIEW_SERVICE_TOKEN"),
            forgejo_url=need("COBBLE_PACK_FORGEJO_URL").rstrip("/"),
            forgejo_token=need("COBBLE_PACK_FORGEJO_TOKEN"),
            forgejo_user=e.get("COBBLE_PACK_FORGEJO_OWNER", "cobble-bot") or "cobble-bot",
            data_dir=Path(e.get("COBBLE_PREVIEW_DATA_DIR", "/data")),
            docker_socket=e.get("COBBLE_PREVIEW_DOCKER_SOCKET", "/var/run/docker.sock"),
            network=e.get("COBBLE_PREVIEW_NETWORK", "cobble_previews"),
            container_port=int(e.get("COBBLE_PREVIEW_CONTAINER_PORT", "8000")),
            memory_mb=int(e.get("COBBLE_PREVIEW_MEMORY_MB", "512")),
            cpus=float(e.get("COBBLE_PREVIEW_CPUS", "1")),
            pids=int(e.get("COBBLE_PREVIEW_PIDS", "256")),
            tmp_mb=int(e.get("COBBLE_PREVIEW_TMP_MB", "64")),
            idle_ttl_s=float(e.get("COBBLE_PREVIEW_IDLE_TTL_S", "1800")),
            reap_interval_s=float(e.get("COBBLE_PREVIEW_REAP_INTERVAL_S", "30")),
            max_running=int(e.get("COBBLE_PREVIEW_MAX_RUNNING", "6")),
            build_timeout_s=float(e.get("COBBLE_PREVIEW_BUILD_TIMEOUT_S", "900")),
            ready_timeout_s=float(e.get("COBBLE_PREVIEW_READY_TIMEOUT_S", "60")),
            max_context_mb=int(e.get("COBBLE_PREVIEW_MAX_CONTEXT_MB", "100")),
            git_rewrite_from=rewrite_from,
            git_rewrite_to=rewrite_to,
            sandbox=_flag(e.get("COBBLE_PREVIEW_SANDBOX", ""), True),
            build_args=build_args,
        )
