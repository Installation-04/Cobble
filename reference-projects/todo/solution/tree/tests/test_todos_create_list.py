import pytest
from fastapi.testclient import TestClient

from app import db
from app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def fresh_db() -> None:
    db.reset()


def test_post_with_a_title_returns_201_and_the_created_todo() -> None:
    response = client.post("/api/todos", json={"title": "Buy milk"})
    assert response.status_code == 201
    body = response.json()
    assert isinstance(body["id"], int)
    assert body["title"] == "Buy milk"
    assert body["done"] is False


def test_post_with_an_empty_title_returns_422() -> None:
    assert client.post("/api/todos", json={"title": ""}).status_code == 422
    assert client.post("/api/todos", json={"title": "   "}).status_code == 422
    assert client.post("/api/todos", json={}).status_code == 422


def test_post_with_a_title_over_200_characters_returns_422() -> None:
    assert client.post("/api/todos", json={"title": "x" * 201}).status_code == 422


def test_get_returns_all_todos_oldest_first() -> None:
    for title in ("first", "second", "third"):
        client.post("/api/todos", json={"title": title})
    response = client.get("/api/todos")
    assert response.status_code == 200
    assert [todo["title"] for todo in response.json()] == ["first", "second", "third"]


def test_get_with_no_todo_returns_an_empty_list() -> None:
    response = client.get("/api/todos")
    assert response.status_code == 200
    assert response.json() == []
