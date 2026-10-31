#!/usr/bin/env python3
"""Create core/.env with random secrets if it does not exist. Never overwrites."""

from __future__ import annotations

import os
import secrets
import sys
from pathlib import Path

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "core" / ".env"


def render() -> str:
    return (
        f"POSTGRES_PASSWORD={secrets.token_hex(16)}\n"
        f"REDIS_PASSWORD={secrets.token_hex(16)}\n"
        f"LITELLM_MASTER_KEY=sk-cobble-{secrets.token_hex(16)}\n"
        "COBBLE_HTTP_PORT=8080\n"
        "COBBLE_LANG=en\n"
    )


def ensure_env(path: Path) -> bool:
    """Return True if the file was created."""
    if path.exists():
        return False
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(render())
    return True


def main(argv: list[str]) -> int:
    path = Path(argv[1]) if len(argv) > 1 else DEFAULT_PATH
    created = ensure_env(path)
    print(f"{path}: {'created' if created else 'kept'}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
