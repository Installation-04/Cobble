"""Shared fixtures of the hidden acceptance tests.

The bench runner copies this file and a project's `hidden/` folder into a temporary directory
that is NOT inside the generated project, then runs pytest there with:

    BENCH_PROJECT_DIR   the root of the generated project (it holds the `app` package)

Every test gets a brand new data directory (`COBBLE_DATA_DIR`) and a brand new working
directory, so an application that stores its data next to the process or under the data
directory starts empty. `launcher.start()` imports the application from scratch, which is how a
restart is simulated: nothing survives in memory.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

PROJECT = Path(os.environ["BENCH_PROJECT_DIR"]).resolve()


def _forget_application() -> None:
    for name in [n for n in sys.modules if n == "app" or n.startswith("app.")]:
        del sys.modules[name]


class Launcher:
    """Starts the application of the project under test, as a fresh process would."""

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self._open: list[TestClient] = []

    def start(self) -> TestClient:
        _forget_application()
        from app.main import app  # noqa: PLC0415 - imported late on purpose

        client = TestClient(app)
        client.__enter__()  # runs the start-up handlers
        self._open.append(client)
        return client

    def stop(self) -> None:
        while self._open:
            self._open.pop().__exit__(None, None, None)
        _forget_application()


@pytest.fixture
def launcher(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Launcher]:
    data = tmp_path / "data"
    data.mkdir()
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    monkeypatch.setenv("COBBLE_DATA_DIR", str(data))
    for name in ("COBBLE_STATIC_DIR", "TODO_SEED"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(cwd)
    monkeypatch.syspath_prepend(str(PROJECT))
    running = Launcher(data)
    yield running
    running.stop()


@pytest.fixture
def client(launcher: Launcher) -> TestClient:
    return launcher.start()
