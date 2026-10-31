from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import db
from app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def fresh_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TODO_DB", str(tmp_path / "todos.db"))
    db.reset()


def test_a_todo_can_be_created_with_a_due_date() -> None:
    response = client.post("/api/todos", json={"title": "Renew passport", "due_date": "2030-05-01"})
    assert response.status_code == 201
    assert response.json()["due_date"] == "2030-05-01"


def test_a_todo_without_a_due_date_has_none() -> None:
    response = client.post("/api/todos", json={"title": "Buy milk"})
    assert response.status_code == 201
    assert response.json()["due_date"] is None


def test_an_invalid_due_date_returns_422() -> None:
    response = client.post("/api/todos", json={"title": "Buy milk", "due_date": "next week"})
    assert response.status_code == 422


def test_the_list_returns_the_due_dates() -> None:
    client.post("/api/todos", json={"title": "Renew passport", "due_date": "2030-05-01"})
    client.post("/api/todos", json={"title": "Buy milk"})
    todos = client.get("/api/todos").json()
    assert [todo["due_date"] for todo in todos] == ["2030-05-01", None]


def test_ticking_a_todo_keeps_its_due_date() -> None:
    created = client.post("/api/todos", json={"title": "Pay rent", "due_date": "2030-06-01"}).json()
    response = client.patch(f"/api/todos/{created['id']}", json={"done": True})
    assert response.json()["due_date"] == "2030-06-01"
