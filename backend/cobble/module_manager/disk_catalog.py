"""The catalogue on disk: `<root>/<id>/manifest.yaml` and the module's compose file.

The root is mounted in the module-manager at the *same absolute path as on the host*: the Docker
daemon resolves bind mounts on the host, so a module's `module_dir` must mean the same path to
both (see core/compose.yml).
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from cobble_sdk import (
    Manifest,
    ManifestError,
    Pack,
    check_pack,
    load_manifest,
    load_packs,
)

log = logging.getLogger(__name__)

Renderer = Callable[[str, str, Mapping[str, str], str | None], dict[str, Any]]


class DiskCatalog:
    def __init__(self, root: str | Path, render: Renderer) -> None:
        self._root = Path(root)
        self._render = render
        self._problems: dict[str, list[str]] = {}

    def manifests(self) -> Mapping[str, Manifest]:
        """Every valid module; the invalid ones are skipped and listed by `problems()`."""
        found: dict[str, Manifest] = {}
        problems: dict[str, list[str]] = {}
        if self._root.is_dir():
            for directory in sorted(p for p in self._root.iterdir() if p.is_dir()):
                path = directory / "manifest.yaml"
                if not path.is_file():
                    continue
                try:
                    manifest = load_manifest(path)
                except ManifestError as exc:
                    problems[directory.name] = list(exc.problems)
                    log.warning(
                        "catalogue: %s is invalid (%d problems)", directory.name, len(exc.problems)
                    )
                    continue
                if manifest.id != directory.name:
                    problems[directory.name] = [f"id: {manifest.id!r} does not match the directory"]
                    continue
                found[manifest.id] = manifest
        self._problems = problems
        return found

    def problems(self) -> dict[str, list[str]]:
        return dict(self._problems)

    def packs(self) -> tuple[dict[str, Pack], dict[str, list[str]]]:
        """The starter packs of `<root>/packs/` that work with this catalogue, and the problems of
        the others (an unreadable file, an unknown module, modules that cannot be installed
        together without a choice)."""
        packs, problems = load_packs(self._root / "packs")
        manifests = self.manifests()
        for pack_id, pack in list(packs.items()):
            issues = check_pack(pack, manifests)
            if issues:
                problems[pack_id] = issues
                del packs[pack_id]
        return packs, problems

    def module_dir(self, module_id: str) -> str:
        return str(self._root / module_id)

    def compose(
        self, module_id: str, variant: str | None, env: Mapping[str, str]
    ) -> dict[str, Any]:
        manifest = self.manifests()[module_id]
        compose_file = manifest.compose
        for candidate in manifest.variants:  # a flavour may bring its own compose file
            if candidate.id == variant and candidate.compose:
                compose_file = candidate.compose
        return self._render(self.module_dir(module_id), compose_file, env, variant)
