from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_returns_ok() -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_is_served_as_json() -> None:
    response = client.get("/api/health")
    assert response.headers["content-type"].startswith("application/json")


def test_application_is_named_after_the_project() -> None:
    assert app.title == "To-do list"
