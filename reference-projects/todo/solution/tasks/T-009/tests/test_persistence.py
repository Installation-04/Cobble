import importlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import config, db
from app.main import app


@pytest.fixture(autouse=True)
def database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "todos.db"
    monkeypatch.setenv("TODO_DB", str(path))
    db.reset()
    return path


def test_the_database_path_comes_from_the_environment(database: Path) -> None:
    assert config.database_path() == database


def test_the_default_database_is_a_file_in_the_data_folder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("TODO_DB")
    assert config.database_path() == Path("data/todos.db")


def test_todos_created_before_a_restart_are_listed_after_it(database: Path) -> None:
    client = TestClient(app)
    client.post("/api/todos", json={"title": "Water the plants"})
    client.post("/api/todos", json={"title": "Pay the rent"})

    importlib.reload(db)  # a restart: nothing stays in the memory of the process

    restarted = TestClient(app)
    titles = [todo["title"] for todo in restarted.get("/api/todos").json()]
    assert titles == ["Water the plants", "Pay the rent"]
    assert database.is_file()


def test_the_done_flag_survives_a_restart() -> None:
    todo = db.create_todo("Buy milk")
    db.set_done(todo.id, True)

    importlib.reload(db)

    stored = db.get_todo(todo.id)
    assert stored is not None
    assert stored.done is True
