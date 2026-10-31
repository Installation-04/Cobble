"""Entry point of the demo container: the API under `/api`, the built frontend under `/`.

Runs `app.seed.seed()` once on the first start. Everything is relative to the page (the
frontend is built with `base: "./"` and calls `api/...`), so the app works behind the prefix
`/demo/<project>/<milestone>/` that Cobble's preview service strips.
"""

from __future__ import annotations

import os
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app import seed
from app.main import app

STATIC_DIR = Path(os.environ.get("COBBLE_STATIC_DIR", "static"))
DATA_DIR = Path(os.environ.get("COBBLE_DATA_DIR", "/tmp"))  # noqa: S108 - tmpfs in the demo


def mount_frontend(application: FastAPI, static_dir: Path) -> bool:
    """Serve the built frontend at `/`, after every API route (so it never shadows them)."""
    if not static_dir.is_dir():
        return False
    if not any(getattr(route, "name", "") == "frontend" for route in application.routes):
        application.mount("/", StaticFiles(directory=static_dir, html=True), name="frontend")
    return True


def seed_once(data_dir: Path) -> bool:
    """Run `seed()` unless it already ran in this data directory. Returns whether it ran."""
    marker = data_dir / ".seeded"
    if marker.exists():
        return False
    seed.seed()
    data_dir.mkdir(parents=True, exist_ok=True)
    marker.write_text("1", encoding="utf-8")
    return True


def main() -> None:
    seed_once(DATA_DIR)
    mount_frontend(app, STATIC_DIR)
    uvicorn.run(
        app,
        host="0.0.0.0",  # noqa: S104 - the container's own network namespace
        port=int(os.environ.get("PORT", "8000")),
        proxy_headers=True,
        forwarded_allow_ips="*",
    )


if __name__ == "__main__":
    main()
