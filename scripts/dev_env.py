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
        f"RUN_TOKEN_SECRET={secrets.token_hex(32)}\n"
        "COBBLE_HTTP_PORT=8080\n"
        "COBBLE_LANG=en\n"
    )


def module_settings(path: Path) -> dict[str, str]:
    """Settings of the module-manager (compose profile `modules`), for the keys still missing."""
    lines = path.read_text(encoding="utf-8").splitlines()
    present = {line.split("=", 1)[0] for line in lines if "=" in line}
    wanted = {"MODULE_MANAGER_TOKEN": secrets.token_hex(32)}
    socket = Path("/var/run/docker.sock")
    if socket.exists():
        wanted["DOCKER_GID"] = str(socket.stat().st_gid)
    wanted["COBBLE_CATALOG_DIR"] = str(DEFAULT_PATH.parent.parent / "catalog")
    return {key: value for key, value in wanted.items() if key not in present}


def ensure_module_settings(path: Path) -> list[str]:
    """Append the module-manager settings that are missing; never changes an existing value."""
    missing = module_settings(path)
    if missing:
        with path.open("a", encoding="utf-8") as handle:
            handle.writelines(f"{key}={value}\n" for key, value in missing.items())
    return sorted(missing)


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
    added = ensure_module_settings(path)
    print(f"{path}: {'created' if created else 'kept'}")
    if added and not created:
        print(f"{path}: added {', '.join(added)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
