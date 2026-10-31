"""To-do list: backend entry point.

Routes live in modules of the `app.api` package: every module that defines a `router` is
mounted here, so a new endpoint is a new file and never an edit of this one.
"""

import importlib
import os
import pkgutil
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from types import ModuleType

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

ASSETS = Path(__file__).resolve().parent.parent / "frontend" / "dist" / "assets"


def _optional_module(name: str) -> ModuleType | None:
    """Import a module that a later task may not have created yet."""
    try:
        return importlib.import_module(name)
    except ModuleNotFoundError as exc:
        if exc.name != name:
            raise
        return None


def _include_routers(application: FastAPI) -> None:
    package = _optional_module("app.api")
    if package is None:
        return
    for info in sorted(pkgutil.iter_modules(package.__path__), key=lambda i: i.name):
        module = importlib.import_module(f"app.api.{info.name}")
        router = getattr(module, "router", None)
        if router is not None:
            application.include_router(router)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """With TODO_SEED=1 an empty store is filled with demo data (previews of a milestone)."""
    seed = _optional_module("app.seed")
    if os.environ.get("TODO_SEED") == "1" and seed is not None:
        seed.seed()
    yield


app = FastAPI(title="To-do list", lifespan=lifespan)
_include_routers(app)
if ASSETS.is_dir():
    app.mount("/assets", StaticFiles(directory=ASSETS), name="assets")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
