"""Hidden acceptance tests: personal blog. They only use the public HTTP API of the spec."""

from __future__ import annotations

from fastapi.testclient import TestClient


def post(client: TestClient, title: str, body: str = "Some text.", **extra) -> dict:  # type: ignore[no-untyped-def]
    response = client.post("/api/posts", json={"title": title, "body": body, **extra})
    assert response.status_code == 201, response.text
    return response.json()


def test_health(client: TestClient) -> None:
    assert client.get("/api/health").status_code == 200


def test_create_returns_the_post(client: TestClient) -> None:
    created = post(client, "Hello World", "First!", tags=["intro"], published=True)
    assert created["slug"] == "hello-world"
    assert created["title"] == "Hello World"
    assert created["body"] == "First!"
    assert created["tags"] == ["intro"]
    assert created["published"] is True
    assert created["comment_count"] == 0
    assert created["created_at"][:2] == "20"  # an ISO 8601 date


def test_a_post_is_a_draft_by_default(client: TestClient) -> None:
    assert post(client, "Secret plans")["published"] is False


def test_slug_removes_punctuation_and_accents(client: TestClient) -> None:
    assert post(client, "Hello, World!")["slug"] == "hello-world"
    assert post(client, "Été à Montréal")["slug"] == "ete-a-montreal"
    assert post(client, "  --Rust & Python: 2 friends--  ")["slug"] == "rust-python-2-friends"


def test_equal_titles_get_numbered_slugs(client: TestClient) -> None:
    slugs = [post(client, "Same title")["slug"] for _ in range(3)]
    assert slugs == ["same-title", "same-title-2", "same-title-3"]


def test_validation(client: TestClient) -> None:
    def create(**fields) -> int:  # type: ignore[no-untyped-def]
        return client.post("/api/posts", json=fields).status_code

    assert create(title="", body="x") == 422
    assert create(title="x" * 121, body="x") == 422
    assert create(title="x" * 120, body="x") == 201
    assert create(title="ok", body="") == 422
    assert create(body="no title") == 422
    assert create(title="tags", body="x", tags=["a", "b", "c", "d", "e", "f"]) == 422
    assert create(title="tags ok", body="x", tags=["a", "b", "c", "d", "e"]) == 201
    assert create(title="Upper", body="x", tags=["Bad Tag"]) == 422


def test_drafts_are_not_public(client: TestClient) -> None:
    post(client, "Draft one")
    post(client, "Public one", published=True)
    assert [p["slug"] for p in client.get("/api/posts").json()] == ["public-one"]
    assert client.get("/api/posts/draft-one").status_code == 404
    assert [p["slug"] for p in client.get("/api/drafts").json()] == ["draft-one"]


def test_publishing_a_draft(client: TestClient) -> None:
    post(client, "Soon")
    response = client.patch("/api/posts/soon", json={"published": True})
    assert response.status_code == 200
    assert response.json()["published"] is True
    assert client.get("/api/posts/soon").status_code == 200
    assert client.get("/api/drafts").json() == []


def test_editing_keeps_the_slug(client: TestClient) -> None:
    post(client, "Old title", published=True)
    response = client.patch("/api/posts/old-title", json={"title": "New title", "body": "Edited"})
    assert response.status_code == 200
    assert response.json()["slug"] == "old-title"
    assert response.json()["title"] == "New title"
    assert client.get("/api/posts/old-title").json()["body"] == "Edited"


def test_list_is_newest_first(client: TestClient) -> None:
    for title in ("first", "second", "third"):
        post(client, title, published=True)
    assert [p["slug"] for p in client.get("/api/posts").json()] == ["third", "second", "first"]


def test_filter_by_tag(client: TestClient) -> None:
    post(client, "A", published=True, tags=["python", "web"])
    post(client, "B", published=True, tags=["web"])
    post(client, "C", published=True)
    post(client, "D", tags=["web"])  # a draft
    assert [p["slug"] for p in client.get("/api/posts?tag=web").json()] == ["b", "a"]
    assert [p["slug"] for p in client.get("/api/posts?tag=python").json()] == ["a"]
    assert client.get("/api/posts?tag=nothing").json() == []


def test_comments(client: TestClient) -> None:
    post(client, "Talk", published=True)
    first = client.post("/api/posts/talk/comments", json={"author": "Ana", "body": "Nice"})
    assert first.status_code == 201
    assert first.json()["author"] == "Ana"
    client.post("/api/posts/talk/comments", json={"author": "Bob", "body": "Agreed"})
    listed = client.get("/api/posts/talk/comments").json()
    assert [(c["author"], c["body"]) for c in listed] == [("Ana", "Nice"), ("Bob", "Agreed")]
    assert client.get("/api/posts/talk").json()["comment_count"] == 2


def test_comment_validation_and_targets(client: TestClient) -> None:
    post(client, "Talk", published=True)
    post(client, "Hidden")
    url = "/api/posts/talk/comments"
    assert client.post(url, json={"author": "", "body": "x"}).status_code == 422
    assert client.post(url, json={"author": "A", "body": ""}).status_code == 422
    assert client.post(url, json={"author": "A", "body": "x" * 1001}).status_code == 422
    assert client.post(url, json={"author": "x" * 51, "body": "x"}).status_code == 422
    missing = client.post("/api/posts/nope/comments", json={"author": "A", "body": "x"})
    assert missing.status_code == 404
    draft = client.post("/api/posts/hidden/comments", json={"author": "A", "body": "x"})
    assert draft.status_code == 404


def test_unknown_post(client: TestClient) -> None:
    assert client.get("/api/posts/missing").status_code == 404
    assert client.patch("/api/posts/missing", json={"published": True}).status_code == 404
    assert client.delete("/api/posts/missing").status_code == 404


def test_delete_removes_the_post_and_its_comments(client: TestClient) -> None:
    post(client, "Short lived", published=True)
    client.post("/api/posts/short-lived/comments", json={"author": "A", "body": "x"})
    assert client.delete("/api/posts/short-lived").status_code == 204
    assert client.get("/api/posts/short-lived").status_code == 404
    again = post(client, "Short lived", published=True)
    assert again["slug"] == "short-lived"
    assert client.get("/api/posts/short-lived/comments").json() == []


def test_data_survives_a_restart(launcher) -> None:  # type: ignore[no-untyped-def]
    first = launcher.start()
    post(first, "Kept", published=True, tags=["x"])
    first.post("/api/posts/kept/comments", json={"author": "A", "body": "hi"})
    post(first, "Still a draft")
    launcher.stop()
    second = launcher.start()
    assert [p["slug"] for p in second.get("/api/posts").json()] == ["kept"]
    assert second.get("/api/posts/kept").json()["comment_count"] == 1
    assert [p["slug"] for p in second.get("/api/drafts").json()] == ["still-a-draft"]
