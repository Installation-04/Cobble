from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_root_returns_200_with_the_html_page() -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")


def test_the_page_contains_the_application_title() -> None:
    assert "To-do list" in client.get("/").text


def test_the_page_can_be_used_on_a_phone() -> None:
    assert 'name="viewport"' in client.get("/").text


def test_an_unknown_page_returns_404() -> None:
    assert client.get("/no-such-page").status_code == 404
