"""Small helpers to build manifests and catalogues for the resolver tests."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from cobble_sdk import Manifest, parse_manifest

DIGEST = "b" * 64


def mod(
    module_id: str,
    *,
    provides: Iterable[str] = (),
    requires: Iterable[str] = (),
    exclusive: Iterable[str] = (),
    gpu: str = "none",
    min_ram_mb: int = 0,
    variants: list[dict[str, Any]] | None = None,
) -> Manifest:
    data: dict[str, Any] = {
        "id": module_id,
        "name": module_id.title(),
        "version": "1.0.0",
        "category": "test",
        "description": {"fr": "Module de test", "en": "Test module"},
        "license": "MIT",
        "provides": list(provides),
        "requires": list(requires),
        "exclusive": list(exclusive),
        "hardware": {"gpu": gpu, "min_ram_mb": min_ram_mb},
        "images": [f"example.org/{module_id}:1.0.0@sha256:{DIGEST}"],
    }
    if variants is not None:
        data["variants"] = variants
    return parse_manifest(data)


def catalog(*manifests: Manifest) -> dict[str, Manifest]:
    return {m.id: m for m in manifests}


def real_shaped() -> dict[str, Manifest]:
    """A catalogue shaped like the v0.2 official one (git, ci, llm, agents)."""
    return catalog(
        mod("forgejo", provides=["git"], exclusive=["git"]),
        mod("gitea", provides=["git"], exclusive=["git"]),
        mod("woodpecker", provides=["ci"], requires=["git"], exclusive=["ci"]),
        mod("litellm", provides=["llm"], exclusive=["llm"]),
        mod("ollama", provides=["llm-backend"], requires=["llm"]),
        mod("agent-service", provides=["agent-runner"], requires=["git", "ci", "llm"]),
        mod("preview-service", provides=["preview"], requires=["git"]),
    )
