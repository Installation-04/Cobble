"""The providers of the modules that are running right now, as the module-manager reports them."""

from __future__ import annotations

from cobble.config import Settings

from .module_manager import HttpModuleManager
from .registry import BuiltProviders, Connection, default_registry
from .settings import load_settings


def build_from_modules(
    settings: Settings, client: HttpModuleManager | None = None
) -> BuiltProviders | None:
    """Providers for the running modules, or None without both a Git and a CI module.

    Raises `ModuleManagerUnavailable` when the module-manager cannot be reached."""
    manager = client or HttpModuleManager.from_settings(settings)
    try:
        raw = manager.connections()
    finally:
        if client is None:
            manager.close()
    connections = {mid: Connection.from_json(mid, data) for mid, data in raw.items()}
    # Defaults for the adapters (branch, merge style, required check...) come from COBBLE_PACK_*.
    return default_registry().build(connections, load_settings())
