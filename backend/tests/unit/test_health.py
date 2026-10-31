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
        "pack_mode": "real",
    }


def test_health_reports_the_fake_pack_mode() -> None:
    from cobble.config import Settings

    app = create_app(
        {"database": ok, "redis": ok}, settings=Settings(pack_mode="fake"), redis=object()
    )
    assert TestClient(app).get("/api/v1/health").json()["pack_mode"] == "fake"


def test_fake_pack_mode_is_refused_in_production() -> None:
    import pytest
    from pydantic import ValidationError

    from cobble.config import Settings

    with pytest.raises(ValidationError, match="production"):
        Settings(pack_mode="fake", env="production")


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
