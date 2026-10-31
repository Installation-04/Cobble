from __future__ import annotations

from fastapi.testclient import TestClient

import cobble
from cobble.api.app import create_app


def ok() -> None:
    return None


def boom() -> None:
    raise ConnectionError("down")


def test_health_ok() -> None:
    client = TestClient(create_app({"database": ok, "redis": ok}))
    reply = client.get("/api/v1/health")
    assert reply.status_code == 200
    assert reply.json() == {
        "status": "ok",
        "database": "ok",
        "redis": "ok",
        "version": cobble.__version__,
    }


def test_health_reports_failing_component_with_503() -> None:
    client = TestClient(create_app({"database": ok, "redis": boom}))
    reply = client.get("/api/v1/health")
    assert reply.status_code == 503
    body = reply.json()
    assert body["status"] == "error"
    assert body["database"] == "ok"
    assert body["redis"] == "error"
    assert "down" not in reply.text, "internal error details must not leak"


def test_openapi_is_versioned() -> None:
    client = TestClient(create_app({"database": ok, "redis": ok}))
    assert "/api/v1/health" in client.get("/api/v1/openapi.json").json()["paths"]
