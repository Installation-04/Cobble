"""Where the manager finds modules: manifests, their compose files, their directories."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from cobble_sdk import Manifest


class CatalogSource(Protocol):
    def manifests(self) -> Mapping[str, Manifest]: ...

    def compose(
        self, module_id: str, variant: str | None, env: Mapping[str, str]
    ) -> dict[str, Any]:
        """The module's compose file as `docker compose config --format json` prints it."""
        ...

    def module_dir(self, module_id: str) -> str: ...


@dataclass
class MemoryCatalog:
    """A catalogue held in memory (tests, and the fake store mode of the browser tests)."""

    modules: dict[str, Manifest]
    composes: dict[str, dict[str, Any]] = field(default_factory=dict)
    root: str = "/opt/cobble/catalog"

    def manifests(self) -> Mapping[str, Manifest]:
        return self.modules

    def compose(
        self, module_id: str, variant: str | None, env: Mapping[str, str]
    ) -> dict[str, Any]:
        manifest = self.modules[module_id]
        if module_id in self.composes:
            return self.composes[module_id]
        service = manifest.web_ui.service if manifest.web_ui else module_id
        return {"services": {service: {"image": manifest.images[0]}}}

    def module_dir(self, module_id: str) -> str:
        return f"{self.root}/{module_id}"
