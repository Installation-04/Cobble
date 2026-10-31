#!/usr/bin/env python3
"""Fail if the fr and en locale files do not have the same files and keys."""

from __future__ import annotations

import json
import sys
from pathlib import Path

LANGS = ("fr", "en")
_REPO = Path(__file__).resolve().parent.parent
DEFAULT_ROOTS = [_REPO / "ui" / "src" / "locales", _REPO / "backend" / "cobble" / "locales"]


def flatten(data: object, prefix: str = "") -> dict[str, object]:
    if isinstance(data, dict):
        out: dict[str, object] = {}
        for key, value in data.items():
            out.update(flatten(value, f"{prefix}.{key}" if prefix else key))
        return out
    return {prefix: data}


def check(root: Path) -> list[str]:
    errors: list[str] = []
    files = {lang: {p.name for p in (root / lang).glob("*.json")} for lang in LANGS}
    for lang in LANGS:
        if not (root / lang).is_dir():
            errors.append(f"missing locale directory: {root / lang}")
    all_names = set().union(*files.values())
    for name in sorted(all_names):
        for lang in LANGS:
            if name not in files[lang]:
                errors.append(f"{lang}/{name}: file missing")
        if all(name in files[lang] for lang in LANGS):
            keys = {}
            for lang in LANGS:
                keys[lang] = flatten(json.loads((root / lang / name).read_text("utf-8")))
            for lang, other in (("fr", "en"), ("en", "fr")):
                for key in sorted(set(keys[other]) - set(keys[lang])):
                    errors.append(f"{lang}/{name}: key missing: {key}")
            for lang in LANGS:
                for key, value in keys[lang].items():
                    if not isinstance(value, str) or not value.strip():
                        errors.append(f"{lang}/{name}: empty or non-string value: {key}")
    return errors


def main(argv: list[str]) -> int:
    roots = [Path(a) for a in argv[1:]] or DEFAULT_ROOTS
    errors = [error for root in roots for error in check(root)]
    for error in errors:
        print(f"i18n: {error}", file=sys.stderr)
    if not errors:
        print("i18n: all keys present in fr and en")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
