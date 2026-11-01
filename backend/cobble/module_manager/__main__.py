"""Start the module-manager: `python -m cobble.module_manager`."""

from __future__ import annotations

import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI
from redis import Redis

from cobble.config import Settings, get_settings
from cobble.db import make_engine, make_session_factory
from cobble.events import publish_module

from .app import create_app
from .disk_catalog import DiskCatalog
from .edge import CaddyEdge, Edge, NullEdge, caddy_reload
from .hardware import host_hardware
from .manager import ModuleManager
from .redaction import RedactingFilter, Redactor
from .runner import ComposeRunner
from .secret_store import SecretStore
from .service import OperationController
from .vault import Vault, VaultError, generate_master_key_file

log = logging.getLogger("cobble.module_manager")
PORT = 8095


def public_env(public_url: str) -> dict[str, str]:
    """How users reach the platform, for modules: `COBBLE_PUBLIC_URL` (no trailing slash), its
    host name and port, and the name under which a gateway answers on the private networks of
    pipelines (the host when it is a name; a fixed name when it is an address, which pipelines
    reach directly)."""
    url = public_url.strip().rstrip("/") or "http://localhost"
    scheme, _, rest = url.partition("://")
    authority = rest.split("/", 1)[0]
    host, _, port = authority.partition(":")
    if not port:
        port = "443" if scheme == "https" else "80"
    is_name = bool(re.search(r"[^0-9.]", host)) and host != "localhost"
    return {
        "COBBLE_PUBLIC_URL": url,
        "COBBLE_PUBLIC_HOST": host,
        "COBBLE_PUBLIC_PORT": port,
        "COBBLE_GATEWAY_ALIAS": host if is_name else "cobble-gateway",
    }


def extra_env(text: str) -> dict[str, str]:
    """Operator-chosen variables for modules, from a JSON object ('' means none)."""
    if not text.strip():
        return {}
    data = json.loads(text)
    if not isinstance(data, dict) or not all(
        isinstance(k, str) and isinstance(v, str) and k.startswith("COBBLE_")
        for k, v in data.items()
    ):
        raise ValueError("COBBLE_MODULE_EXTRA_ENV must be a JSON object of COBBLE_* strings")
    return data


def docker_gid(socket: str = "/var/run/docker.sock") -> str:
    """Group that owns the Docker socket, for modules that must be allowed to use it."""
    try:
        return str(os.stat(socket).st_gid)
    except OSError:
        return "0"


def build_app(settings: Settings, redis: Redis) -> tuple[FastAPI, ModuleManager]:
    key_file = Path(settings.module_master_key_file)
    if not key_file.exists():
        key_file.parent.mkdir(parents=True, exist_ok=True)
        generate_master_key_file(key_file)  # first start: the key is born here and stays here
        log.info("created the vault master key")
    vault = Vault.from_file(key_file)
    redactor = Redactor()
    for handler in logging.getLogger().handlers:
        handler.addFilter(RedactingFilter(redactor))
    runner = ComposeRunner()
    catalog = DiskCatalog(settings.module_catalog_dir, runner.render)

    def publish(kind: str, payload: dict[str, Any]) -> None:
        publish_module(redis, kind, payload)

    edge: Edge = NullEdge()
    if settings.module_routes_dir:
        edge = CaddyEdge(
            Path(settings.module_routes_dir),
            Path(settings.module_caddyfile),
            caddy_reload(Path(settings.module_caddy_admin_socket)),
        )
    controller = OperationController(publish)
    manager = ModuleManager(
        make_session_factory(make_engine(settings.database_url)),
        catalog,
        runner,
        SecretStore(vault, redactor),
        host_hardware(settings.module_ram_mb, settings.module_gpu),
        health_timeout_s=settings.module_health_timeout_s,
        on_event=controller.on_step,
        edge=edge,
        platform_env={
            **extra_env(settings.module_extra_env),
            **public_env(settings.module_public_url),
            "COBBLE_DOCKER_GID": docker_gid(),
        },
    )
    controller.bind(manager)
    return create_app(controller, settings.module_manager_token, catalog), manager


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    settings = get_settings()
    if not settings.module_manager_token:
        log.error("COBBLE_MODULE_MANAGER_TOKEN is not set: refusing to start")
        return 78
    try:
        app, manager = build_app(settings, Redis.from_url(settings.redis_url))
    except VaultError as exc:
        log.error("the vault cannot start: %s", exc.code)
        return 78
    recovered = manager.recover()  # a crash may have left modules half installed or removed
    if recovered:
        log.warning("recovered after an interruption: %s", ", ".join(recovered))
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="info")  # noqa: S104 - internal network only
    return 0


if __name__ == "__main__":
    sys.exit(main())
