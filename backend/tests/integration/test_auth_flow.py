from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from redis import Redis
from sqlalchemy import text

from cobble.api.app import create_app
from cobble.auth.activation import create_activation_token
from cobble.config import Settings
from cobble.db import make_engine, make_session_factory

pytestmark = pytest.mark.integration

H = {"X-Requested-With": "cobble"}
API = "/api/v1"
PASSWORD = "integration-password"


def test_activate_login_folder_project_flow(migrated_database: str, redis_url: str) -> None:
    engine = make_engine(migrated_database)
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM users"))  # cascades to sessions/folders/projects
        connection.execute(text("DELETE FROM activation_tokens"))
    sessions = make_session_factory(engine)
    settings = Settings(database_url=migrated_database, redis_url=redis_url)
    client = TestClient(create_app(settings=settings, session_factory=sessions))
    email = f"admin-{uuid.uuid4().hex[:8]}@example.com"

    assert client.get(f"{API}/setup/status").json() == {"initialized": False}
    with sessions() as db:
        raw, _ = create_activation_token(db)

    reply = client.post(
        f"{API}/auth/activate",
        json={"token": raw, "email": email, "password": PASSWORD, "lang": "fr"},
        headers=H,
    )
    assert reply.status_code == 201, reply.text
    assert client.get(f"{API}/setup/status").json() == {"initialized": True}
    assert client.get(f"{API}/auth/me").json()["email"] == email

    assert client.post(f"{API}/auth/logout", headers=H).status_code == 204
    assert client.get(f"{API}/auth/me").status_code == 401

    bad = client.post(f"{API}/auth/login", json={"email": email, "password": "x"}, headers=H)
    assert bad.status_code == 401
    ok = client.post(f"{API}/auth/login", json={"email": email, "password": PASSWORD}, headers=H)
    assert ok.status_code == 200

    folder = client.post(f"{API}/folders", json={"name": "Work"}, headers=H).json()
    project = client.post(
        f"{API}/projects", json={"name": "App", "folder_id": folder["id"]}, headers=H
    ).json()
    assert project["folder_id"] == folder["id"]

    # The database enforces ON DELETE SET NULL as well as the application.
    assert client.delete(f"{API}/folders/{folder['id']}", headers=H).status_code == 204
    projects = client.get(f"{API}/projects").json()
    assert [(p["id"], p["folder_id"]) for p in projects] == [(project["id"], None)]

    with sessions() as db:
        stored = db.execute(text("SELECT password_hash FROM users")).scalar_one()
    assert stored.startswith("scrypt$") and PASSWORD not in stored


def test_rate_limit_uses_real_redis(migrated_database: str, redis_url: str) -> None:
    redis = Redis.from_url(redis_url)
    settings = Settings(database_url=migrated_database, redis_url=redis_url)
    sessions = make_session_factory(make_engine(migrated_database))
    client = TestClient(create_app(settings=settings, session_factory=sessions, redis=redis))
    email = f"nobody-{uuid.uuid4().hex[:8]}@example.com"
    statuses = [
        client.post(
            f"{API}/auth/login", json={"email": email, "password": "bad"}, headers=H
        ).status_code
        for _ in range(6)
    ]
    assert statuses == [401] * 5 + [429]
