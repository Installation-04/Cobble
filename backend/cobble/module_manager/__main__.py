"""Start the module-manager: `python -m cobble.module_manager`."""

from __future__ import annotations

import logging
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
from .hardware import host_hardware
from .manager import ModuleManager
from .redaction import RedactingFilter, Redactor
from .runner import ComposeRunner
from .secret_store import SecretStore
from .service import OperationController
from .vault import Vault, VaultError, generate_master_key_file

log = logging.getLogger("cobble.module_manager")
PORT = 8095


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

    controller = OperationController(publish)
    manager = ModuleManager(
        make_session_factory(make_engine(settings.database_url)),
        catalog,
        runner,
        SecretStore(vault, redactor),
        host_hardware(settings.module_ram_mb, settings.module_gpu),
        health_timeout_s=settings.module_health_timeout_s,
        on_event=controller.on_step,
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
