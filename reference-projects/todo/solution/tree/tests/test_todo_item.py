import pytest
from fastapi.testclient import TestClient

from app import db
from app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def fresh_db() -> None:
    db.reset()


def test_patch_with_done_true_returns_200_and_the_todo_marked_done() -> None:
    todo = db.create_todo("Buy milk")
    response = client.patch(f"/api/todos/{todo.id}", json={"done": True})
    assert response.status_code == 200
    body = response.json()
    assert (body["id"], body["title"], body["done"]) == (todo.id, "Buy milk", True)
    assert db.get_todo(todo.id) == todo.model_copy(update={"done": True})


def test_patch_with_done_false_unticks_the_todo() -> None:
    todo = db.create_todo("Buy milk")
    db.set_done(todo.id, True)
    response = client.patch(f"/api/todos/{todo.id}", json={"done": False})
    assert response.status_code == 200
    assert response.json()["done"] is False


def test_patch_without_done_returns_422() -> None:
    todo = db.create_todo("Buy milk")
    assert client.patch(f"/api/todos/{todo.id}", json={}).status_code == 422


def test_delete_returns_204_and_the_todo_is_gone() -> None:
    kept = db.create_todo("Keep me")
    gone = db.create_todo("Delete me")
    response = client.delete(f"/api/todos/{gone.id}")
    assert response.status_code == 204
    assert response.content == b""
    assert db.list_todos() == [kept]


def test_patch_or_delete_on_an_unknown_id_returns_404() -> None:
    assert client.patch("/api/todos/999", json={"done": True}).status_code == 404
    assert client.delete("/api/todos/999").status_code == 404
