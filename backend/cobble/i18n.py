"""Minimal translations for the CLI and user-facing API messages (fr and en)."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

LOCALES = Path(__file__).parent / "locales"
SUPPORTED = ("fr", "en")
FALLBACK = "en"


def _flatten(data: dict[str, Any], prefix: str = "") -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in data.items():
        name = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            out.update(_flatten(value, name))
        else:
            out[name] = str(value)
    return out


@lru_cache
def _catalog(lang: str) -> dict[str, str]:
    catalog: dict[str, str] = {}
    for path in sorted((LOCALES / lang).glob("*.json")):
        catalog.update(_flatten(json.loads(path.read_text("utf-8"))))
    return catalog


def t(key: str, lang: str = FALLBACK, **params: object) -> str:
    """Translate `key`; unknown language falls back to English, unknown key to the key."""
    chosen = lang if lang in SUPPORTED else FALLBACK
    template = _catalog(chosen).get(key) or _catalog(FALLBACK).get(key) or key
    return template.format(**params)
