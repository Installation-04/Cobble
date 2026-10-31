#!/usr/bin/env python3
"""Fail if a color literal appears in ui/src outside the theme token file.

Colors must come from CSS variable tokens (ui/src/styles/tokens.css) so that light and
dark modes stay consistent. Flagged: #hex, rgb()/hsl()/oklch()... functions and Tailwind
palette classes such as ``bg-red-500`` or ``text-white``.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
DEFAULT_ROOT = _REPO / "ui" / "src"
TOKEN_FILE = Path("styles") / "tokens.css"
SCANNED_SUFFIXES = {".ts", ".tsx", ".js", ".jsx", ".css", ".html", ".svg", ".json", ".md"}

_PALETTE = (
    "slate|gray|zinc|neutral|stone|red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky"
    "|blue|indigo|violet|purple|fuchsia|pink|rose"
)
_UTILITIES = (
    "bg|text|border|ring|ring-offset|fill|stroke|from|via|to|outline|divide|decoration"
    "|shadow|accent|caret|placeholder"
)
PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("hex color", re.compile(r"(?<![\w&])#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3,4})\b")),
    (
        "color function",
        re.compile(r"\b(?:rgba?|hsla?|hwb|lab|lch|oklab|oklch)\(", re.IGNORECASE),
    ),
    (
        "tailwind palette class",
        re.compile(rf"(?<![\w-])(?:{_UTILITIES})-(?:{_PALETTE})-\d{{2,3}}(?![\w-])"),
    ),
    (
        "tailwind black/white class",
        re.compile(rf"(?<![\w-])(?:{_UTILITIES})-(?:black|white)(?![\w-])"),
    ),
]


def check(root: Path) -> list[str]:
    """Return one message per offending line, as ``path:line: kind: text``."""
    errors: list[str] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix not in SCANNED_SUFFIXES:
            continue
        if "node_modules" in path.parts or path.relative_to(root) == TOKEN_FILE:
            continue
        text = path.read_text("utf-8", errors="ignore")
        for number, line in enumerate(text.splitlines(), start=1):
            for kind, pattern in PATTERNS:
                match = pattern.search(line)
                if match:
                    errors.append(f"{path.relative_to(root)}:{number}: {kind}: {match.group(0)}")
    return errors


def main(argv: list[str]) -> int:
    root = Path(argv[1]) if len(argv) > 1 else DEFAULT_ROOT
    errors = check(root)
    for error in errors:
        print(f"colors: {error}", file=sys.stderr)
    if errors:
        print("colors: use theme tokens (see ui/src/styles/tokens.css)", file=sys.stderr)
        return 1
    print("colors: no hardcoded color outside the token file")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
