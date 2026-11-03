"""`python -m cobble_sdk.schema [--check]`: write or verify the JSON Schemas in `schema/`."""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .manifest import manifest_json_schema
from .packs import pack_json_schema

SCHEMAS = Path(__file__).resolve().parent.parent / "schema"
TARGET = SCHEMAS / "manifest.schema.json"  # kept for callers of the former single schema
TARGETS = {
    SCHEMAS / "manifest.schema.json": manifest_json_schema,
    SCHEMAS / "pack.schema.json": pack_json_schema,
}


def render(build: Callable[[], dict[str, Any]] = manifest_json_schema) -> str:
    return json.dumps(build(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main(argv: list[str]) -> int:
    if "--check" in argv:
        stale = [
            path
            for path, build in TARGETS.items()
            if not path.exists() or path.read_text("utf-8") != render(build)
        ]
        for path in stale:
            print(f"{path} is out of date: run `python -m cobble_sdk.schema`", file=sys.stderr)
        return 1 if stale else 0
    for path, build in TARGETS.items():
        path.write_text(render(build), "utf-8")
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
