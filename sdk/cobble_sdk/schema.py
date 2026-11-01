"""`python -m cobble_sdk.schema [--check]`: write or verify `schema/manifest.schema.json`."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from .manifest import manifest_json_schema

TARGET = Path(__file__).resolve().parent.parent / "schema" / "manifest.schema.json"


def render() -> str:
    return json.dumps(manifest_json_schema(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main(argv: list[str]) -> int:
    if "--check" in argv:
        if not TARGET.exists() or TARGET.read_text("utf-8") != render():
            print(f"{TARGET} is out of date: run `python -m cobble_sdk.schema`", file=sys.stderr)
            return 1
        return 0
    TARGET.write_text(render(), "utf-8")
    print(f"wrote {TARGET}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
