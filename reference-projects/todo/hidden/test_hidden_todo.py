"""Hidden acceptance tests: to-do list. They only use the public HTTP API of the spec."""

from __future__ import annotations

from fastapi.testclient import TestClient


def add(client: TestClient, title: str) -> dict:
    response = client.post("/api/todos", json={"title": title})
    assert response.status_code == 201, response.text
    return response.json()


def test_health(client: TestClient) -> None:
    assert client.get("/api/health").status_code == 200


def test_create_returns_the_new_todo(client: TestClient) -> None:
    todo = add(client, "Buy milk")
    assert todo["title"] == "Buy milk"
    assert todo["done"] is False
    assert isinstance(todo["id"], int)


def test_ids_are_distinct(client: TestClient) -> None:
    assert add(client, "a")["id"] != add(client, "b")["id"]


def test_empty_or_missing_title_is_rejected(client: TestClient) -> None:
    assert client.post("/api/todos", json={"title": ""}).status_code == 422
    assert client.post("/api/todos", json={}).status_code == 422


def test_title_length_bounds(client: TestClient) -> None:
    assert client.post("/api/todos", json={"title": "x" * 200}).status_code == 201
    assert client.post("/api/todos", json={"title": "x" * 201}).status_code == 422


def test_list_is_empty_at_first(client: TestClient) -> None:
    response = client.get("/api/todos")
    assert response.status_code == 200
    assert response.json() == []


def test_list_is_oldest_first(client: TestClient) -> None:
    for title in ("first", "second", "third"):
        add(client, title)
    assert [t["title"] for t in client.get("/api/todos").json()] == ["first", "second", "third"]


def test_tick_and_untick(client: TestClient) -> None:
    todo = add(client, "Pay the rent")
    ticked = client.patch(f"/api/todos/{todo['id']}", json={"done": True})
    assert ticked.status_code == 200
    assert ticked.json()["done"] is True
    assert client.get("/api/todos").json()[0]["done"] is True
    unticked = client.patch(f"/api/todos/{todo['id']}", json={"done": False})
    assert unticked.json()["done"] is False


def test_tick_touches_only_that_todo(client: TestClient) -> None:
    a, b = add(client, "a"), add(client, "b")
    client.patch(f"/api/todos/{a['id']}", json={"done": True})
    states = {t["title"]: t["done"] for t in client.get("/api/todos").json()}
    assert states == {"a": True, "b": False}
    assert b["done"] is False


def test_delete(client: TestClient) -> None:
    a, b = add(client, "a"), add(client, "b")
    assert client.delete(f"/api/todos/{a['id']}").status_code == 204
    assert [t["id"] for t in client.get("/api/todos").json()] == [b["id"]]


def test_unknown_id_is_404(client: TestClient) -> None:
    assert client.patch("/api/todos/9999", json={"done": True}).status_code == 404
    assert client.delete("/api/todos/9999").status_code == 404


def test_deleting_twice_is_404(client: TestClient) -> None:
    todo = add(client, "once")
    assert client.delete(f"/api/todos/{todo['id']}").status_code == 204
    assert client.delete(f"/api/todos/{todo['id']}").status_code == 404


def test_data_survives_a_restart(launcher) -> None:  # type: ignore[no-untyped-def]
    first = launcher.start()
    kept = add(first, "Water the plants")
    gone = add(first, "Throw away")
    first.patch(f"/api/todos/{kept['id']}", json={"done": True})
    first.delete(f"/api/todos/{gone['id']}")
    launcher.stop()
    second = launcher.start()
    todos = second.get("/api/todos").json()
    assert [(t["title"], t["done"]) for t in todos] == [("Water the plants", True)]


def test_the_page_is_served(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "html" in response.headers["content-type"]
