#!/usr/bin/env python3
"""Pin the images this repository publishes (`images.yml`) in the catalogue.

    scripts/pin_images.py ghcr.io/owner/cobble-agent-service@sha256:<digest> ...
    scripts/pin_images.py --from-dir digests/        # the files the workflow uploads

Every reference to `ghcr.io/<owner>/cobble-<name>[:tag]@sha256:<64 hex>` under `catalog/`
(manifests, compose files, hooks) is replaced by the new one for the same <name>. Nothing else is touched.
Exit code 1 when a given name appears nowhere (a typo, or a module that does not use it yet).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

CATALOG = Path(__file__).resolve().parent.parent / "catalog"
REFERENCE = re.compile(r"^ghcr\.io/([a-z0-9][a-z0-9-]*)/cobble-([a-z0-9-]+)@(sha256:[0-9a-f]{64})$")
SUFFIXES = {".yaml", ".yml", ".sh"}


def parse(references: list[str]) -> dict[str, str]:
    """name -> full reference."""
    pinned: dict[str, str] = {}
    for ref in references:
        match = REFERENCE.match(ref.strip())
        if match is None:
            raise ValueError(f"not an image reference with a digest: {ref!r}")
        pinned[match.group(2)] = ref.strip()
    return pinned


def rewrite(text: str, pinned: dict[str, str]) -> tuple[str, set[str]]:
    used: set[str] = set()

    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in pinned:
            return match.group(0)
        used.add(name)
        return pinned[name]

    pattern = re.compile(
        r"ghcr\.io/[a-z0-9][a-z0-9-]*/cobble-([a-z0-9-]+)(?::[A-Za-z0-9_.-]+)?@sha256:[0-9a-f]{64}"
    )
    return pattern.sub(replace, text), used


def pin(catalog: Path, pinned: dict[str, str]) -> tuple[list[Path], set[str]]:
    changed: list[Path] = []
    used: set[str] = set()
    for path in sorted(p for p in catalog.rglob("*") if p.is_file() and p.suffix in SUFFIXES):
        before = path.read_text("utf-8")
        after, names = rewrite(before, pinned)
        used |= names
        if after != before:
            path.write_text(after, "utf-8")
            changed.append(path)
    return changed, used


def main(argv: list[str]) -> int:
    references: list[str] = []
    args = iter(argv)
    for arg in args:
        if arg == "--from-dir":
            references += [
                line.strip()
                for file in sorted(Path(next(args)).rglob("*.txt"))
                for line in file.read_text("utf-8").splitlines()
                if line.strip()
            ]
        else:
            references.append(arg)
    if not references:
        print(__doc__, file=sys.stderr)
        return 2
    try:
        pinned = parse(references)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2
    changed, used = pin(CATALOG, pinned)
    for path in changed:
        print(f"pinned {path.relative_to(CATALOG.parent)}")
    missing = sorted(set(pinned) - used)
    for name in missing:
        print(f"cobble-{name}: not referenced anywhere in catalog/", file=sys.stderr)
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
