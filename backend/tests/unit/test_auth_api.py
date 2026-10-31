from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from cobble.api.app import create_app
from cobble.auth.activation import create_activation_token
from cobble.auth.tokens import hash_token, utcnow
from cobble.config import Settings
from cobble.db import ActivationToken, AuthSession, Base, User, make_session_factory

from .fakes import CounterRedis

H = {"X-Requested-With": "cobble"}
API = "/api/v1"
PASSWORD = "s3cret-password"


@pytest.fixture
def sessions() -> Iterator[sessionmaker[Session]]:
    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    yield make_session_factory(engine)
    engine.dispose()


@pytest.fixture
def redis() -> CounterRedis:
    return CounterRedis()


@pytest.fixture
def client(sessions: sessionmaker[Session], redis: CounterRedis) -> TestClient:
    app = create_app(
        {"database": lambda: None, "redis": lambda: None},
        settings=Settings(),
        session_factory=sessions,
        redis=redis,
    )
    return TestClient(app)


def token(sessions: sessionmaker[Session]) -> str:
    with sessions() as db:
        return create_activation_token(db)[0]


def activate(
    client: TestClient,
    sessions: sessionmaker[Session],
    email: str = "Admin@Example.com",
    **extra: object,
) -> object:
    body = {"token": token(sessions), "email": email, "password": PASSWORD, **extra}
    return client.post(f"{API}/auth/activate", json=body, headers=H)


@pytest.fixture
def logged(client: TestClient, sessions: sessionmaker[Session]) -> TestClient:
    assert activate(client, sessions).status_code == 201  # type: ignore[attr-defined]
    return client


def code(reply: object) -> str:
    return reply.json()["error"]["code"]  # type: ignore[attr-defined]


# --- setup and activation -------------------------------------------------


def test_setup_status_flips_after_activation(
    client: TestClient, sessions: sessionmaker[Session]
) -> None:
    assert client.get(f"{API}/setup/status").json() == {"initialized": False}
    activate(client, sessions)
    assert client.get(f"{API}/setup/status").json() == {"initialized": True}


def test_activate_creates_user_and_session_cookie(
    client: TestClient, sessions: sessionmaker[Session]
) -> None:
    reply = client.post(
        f"{API}/auth/activate",
        json={
            "token": token(sessions),
            "email": " Admin@Example.com ",
            "password": PASSWORD,
            "lang": "fr",
        },
        headers=H,
    )
    assert reply.status_code == 201
    user = reply.json()
    assert user["email"] == "admin@example.com"
    assert user["role"] == "admin"
    assert user["lang"] == "fr"
    assert user["theme"] == "system"
    assert "password" not in reply.text
    assert client.get(f"{API}/auth/me").json() == user


def test_activate_defaults_lang_to_en(client: TestClient, sessions: sessionmaker[Session]) -> None:
    reply = activate(client, sessions)
    assert reply.json()["lang"] == "en"  # type: ignore[attr-defined]


def test_cookie_flags(sessions: sessionmaker[Session]) -> None:
    app = create_app(
        {"database": lambda: None, "redis": lambda: None},
        settings=Settings(cookie_secure=True),
        session_factory=sessions,
        redis=CounterRedis(),
    )
    reply = activate(TestClient(app), sessions)
    header = reply.headers["set-cookie"].lower()  # type: ignore[attr-defined]
    assert header.startswith("cobble_session=")
    for flag in ("httponly", "samesite=lax", "path=/", "secure", f"max-age={7 * 24 * 3600}"):
        assert flag in header


def test_cookie_not_secure_by_default(sessions: sessionmaker[Session]) -> None:
    app = create_app(
        {"database": lambda: None, "redis": lambda: None},
        settings=Settings(),
        session_factory=sessions,
        redis=CounterRedis(),
    )
    reply = activate(TestClient(app), sessions)
    assert "secure" not in reply.headers["set-cookie"].lower()  # type: ignore[attr-defined]


def test_only_hashes_are_stored(client: TestClient, sessions: sessionmaker[Session]) -> None:
    raw = token(sessions)
    client.post(
        f"{API}/auth/activate",
        json={"token": raw, "email": "a@b.co", "password": PASSWORD},
        headers=H,
    )
    cookie = client.cookies["cobble_session"]
    with sessions() as db:
        assert db.scalars(select(ActivationToken.token_hash)).all() == [hash_token(raw)]
        assert db.scalars(select(AuthSession.token_hash)).all() == [hash_token(cookie)]


def test_activate_invalid_token(client: TestClient) -> None:
    reply = client.post(
        f"{API}/auth/activate",
        json={"token": "nope", "email": "a@b.co", "password": PASSWORD},
        headers=H,
    )
    assert reply.status_code == 400
    assert reply.json() == {"error": {"code": "activation_invalid", "params": {}}}


def test_activate_expired_token(client: TestClient, sessions: sessionmaker[Session]) -> None:
    with sessions() as db:
        raw, _ = create_activation_token(db, utcnow() - timedelta(hours=25))
    reply = client.post(
        f"{API}/auth/activate",
        json={"token": raw, "email": "a@b.co", "password": PASSWORD},
        headers=H,
    )
    assert reply.status_code == 410
    assert code(reply) == "activation_expired"


def test_activate_token_is_single_use(client: TestClient, sessions: sessionmaker[Session]) -> None:
    raw = token(sessions)
    body = {"token": raw, "email": "a@b.co", "password": PASSWORD}
    assert client.post(f"{API}/auth/activate", json=body, headers=H).status_code == 201
    # Same token again: the instance is now initialized.
    assert client.post(f"{API}/auth/activate", json=body, headers=H).status_code == 409


def test_used_token_is_invalid_when_no_user_exists(
    client: TestClient, sessions: sessionmaker[Session]
) -> None:
    raw = token(sessions)
    with sessions() as db:
        row = db.scalars(select(ActivationToken)).one()
        row.used_at = utcnow()
        db.commit()
    reply = client.post(
        f"{API}/auth/activate",
        json={"token": raw, "email": "a@b.co", "password": PASSWORD},
        headers=H,
    )
    assert code(reply) == "activation_invalid"


def test_activate_already_initialized(logged: TestClient, sessions: sessionmaker[Session]) -> None:
    reply = logged.post(
        f"{API}/auth/activate",
        json={"token": token(sessions), "email": "x@y.zz", "password": PASSWORD},
        headers=H,
    )
    assert reply.status_code == 409
    assert code(reply) == "already_initialized"


def test_activate_validation(client: TestClient, sessions: sessionmaker[Session]) -> None:
    reply = client.post(
        f"{API}/auth/activate",
        json={"token": token(sessions), "email": "not-an-email", "password": "short"},
        headers=H,
    )
    assert reply.status_code == 422
    assert reply.json()["error"]["code"] == "validation_error"
    assert reply.json()["error"]["params"]["fields"] == ["email", "password"]


# --- login / logout / me ---------------------------------------------------


def test_login_ok_sets_new_session(logged: TestClient) -> None:
    other = TestClient(logged.app)
    reply = other.post(
        f"{API}/auth/login", json={"email": "ADMIN@example.com", "password": PASSWORD}, headers=H
    )
    assert reply.status_code == 200
    assert reply.json()["email"] == "admin@example.com"
    assert other.get(f"{API}/auth/me").status_code == 200


def test_login_bad_password_and_unknown_user_look_the_same(logged: TestClient) -> None:
    bad = logged.post(
        f"{API}/auth/login", json={"email": "admin@example.com", "password": "nope"}, headers=H
    )
    unknown = logged.post(
        f"{API}/auth/login", json={"email": "who@example.com", "password": "nope"}, headers=H
    )
    assert bad.status_code == unknown.status_code == 401
    assert bad.json() == unknown.json() == {"error": {"code": "invalid_credentials", "params": {}}}


def test_login_rate_limit_and_reset(logged: TestClient, redis: CounterRedis) -> None:
    def attempt(password: str, email: str = "admin@example.com") -> int:
        return logged.post(
            f"{API}/auth/login", json={"email": email, "password": password}, headers=H
        ).status_code

    assert [attempt("bad") for _ in range(5)] == [401] * 5
    assert list(redis.ttl.values()) == [15 * 60]
    blocked = logged.post(
        f"{API}/auth/login", json={"email": "admin@example.com", "password": PASSWORD}, headers=H
    )
    assert blocked.status_code == 429
    assert code(blocked) == "too_many_attempts"
    # Another email is not affected.
    assert attempt("bad", "other@example.com") == 401


def test_login_success_resets_counter(logged: TestClient, redis: CounterRedis) -> None:
    for _ in range(4):
        logged.post(
            f"{API}/auth/login", json={"email": "admin@example.com", "password": "bad"}, headers=H
        )
    assert redis.values
    ok = logged.post(
        f"{API}/auth/login", json={"email": "admin@example.com", "password": PASSWORD}, headers=H
    )
    assert ok.status_code == 200
    assert not redis.values


def test_login_fails_open_when_redis_is_down(
    sessions: sessionmaker[Session], caplog: pytest.LogCaptureFixture
) -> None:
    app = create_app(
        {"database": lambda: None, "redis": lambda: None},
        settings=Settings(),
        session_factory=sessions,
        redis=CounterRedis(fail=True),
    )
    client = TestClient(app)
    activate(client, sessions)
    reply = client.post(
        f"{API}/auth/login", json={"email": "admin@example.com", "password": PASSWORD}, headers=H
    )
    assert reply.status_code == 200
    assert "failing open" in caplog.text


def test_logout_invalidates_session(logged: TestClient, sessions: sessionmaker[Session]) -> None:
    stolen = logged.cookies["cobble_session"]
    assert logged.post(f"{API}/auth/logout", headers=H).status_code == 204
    with sessions() as db:
        assert db.scalars(select(AuthSession)).all() == []
    logged.cookies.set("cobble_session", stolen)
    assert logged.get(f"{API}/auth/me").status_code == 401


def test_logout_without_session_is_204(client: TestClient) -> None:
    assert client.post(f"{API}/auth/logout", headers=H).status_code == 204


def test_me_requires_authentication(client: TestClient) -> None:
    reply = client.get(f"{API}/auth/me")
    assert reply.status_code == 401
    assert reply.json() == {"error": {"code": "unauthenticated", "params": {}}}


def test_expired_session_is_rejected_and_removed(
    logged: TestClient, sessions: sessionmaker[Session]
) -> None:
    with sessions() as db:
        row = db.scalars(select(AuthSession)).one()
        row.expires_at = utcnow() - timedelta(seconds=1)
        db.commit()
    assert logged.get(f"{API}/auth/me").status_code == 401
    with sessions() as db:
        assert db.scalars(select(AuthSession)).all() == []


def test_session_is_extended_on_use(logged: TestClient, sessions: sessionmaker[Session]) -> None:
    with sessions() as db:
        row = db.scalars(select(AuthSession)).one()
        row.expires_at = utcnow() + timedelta(hours=1)
        db.commit()
    logged.get(f"{API}/auth/me")
    with sessions() as db:
        row = db.scalars(select(AuthSession)).one()
        assert row.expires_at.replace(tzinfo=None) > (utcnow() + timedelta(days=6)).replace(
            tzinfo=None
        )


def test_patch_me(logged: TestClient) -> None:
    reply = logged.patch(f"{API}/auth/me", json={"lang": "fr", "theme": "dark"}, headers=H)
    assert reply.status_code == 200
    assert reply.json()["lang"] == "fr"
    assert reply.json()["theme"] == "dark"
    assert logged.get(f"{API}/auth/me").json()["theme"] == "dark"
    partial = logged.patch(f"{API}/auth/me", json={"theme": "light"}, headers=H).json()
    assert partial["lang"] == "fr"
    assert partial["theme"] == "light"


def test_patch_me_validation_and_auth(logged: TestClient, client: TestClient) -> None:
    reply = logged.patch(f"{API}/auth/me", json={"lang": "de"}, headers=H)
    assert reply.status_code == 422
    assert reply.json()["error"]["params"]["fields"] == ["lang"]
    fresh = TestClient(client.app)
    assert fresh.patch(f"{API}/auth/me", json={"lang": "fr"}, headers=H).status_code == 401


# --- CSRF and error format ---------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("post", "/auth/login"),
        ("post", "/auth/activate"),
        ("post", "/auth/logout"),
        ("patch", "/auth/me"),
        ("post", "/folders"),
        ("delete", "/folders/x"),
        ("post", "/projects"),
    ],
)
def test_csrf_header_required_on_unsafe_methods(logged: TestClient, method: str, path: str) -> None:
    reply = logged.request(method, API + path, json={})
    assert reply.status_code == 403
    assert reply.json() == {"error": {"code": "csrf_failed", "params": {}}}
    wrong = logged.request(method, API + path, json={}, headers={"X-Requested-With": "other"})
    assert wrong.status_code == 403


def test_safe_methods_need_no_csrf_header(logged: TestClient) -> None:
    assert logged.get(f"{API}/folders").status_code == 200


def test_unknown_route_and_method_use_error_format(client: TestClient) -> None:
    missing = client.get(f"{API}/nothing")
    assert missing.status_code == 404
    assert missing.json() == {"error": {"code": "not_found", "params": {}}}
    wrong = client.get(f"{API}/auth/login")
    assert wrong.status_code == 405
    assert code(wrong) == "method_not_allowed"


# --- folders and projects --------------------------------------------------------


def test_folders_crud_and_positions(logged: TestClient) -> None:
    first = logged.post(f"{API}/folders", json={"name": "  Work  "}, headers=H)
    second = logged.post(f"{API}/folders", json={"name": "Home"}, headers=H)
    assert first.status_code == 201
    assert first.json()["name"] == "Work"
    assert second.json()["position"] == first.json()["position"] + 1
    listing = logged.get(f"{API}/folders").json()
    assert [f["name"] for f in listing] == ["Work", "Home"]
    assert set(listing[0]) == {"id", "name", "position"}

    renamed = logged.patch(f"{API}/folders/{first.json()['id']}", json={"name": "Job"}, headers=H)
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "Job"

    deleted = logged.delete(f"{API}/folders/{first.json()['id']}", headers=H)
    assert deleted.status_code == 204
    assert [f["name"] for f in logged.get(f"{API}/folders").json()] == ["Home"]
    assert logged.delete(f"{API}/folders/{first.json()['id']}", headers=H).status_code == 404


@pytest.mark.parametrize("name", ["", "   ", "x" * 101])
def test_folder_name_validation(logged: TestClient, name: str) -> None:
    reply = logged.post(f"{API}/folders", json={"name": name}, headers=H)
    assert reply.status_code == 422
    assert reply.json() == {"error": {"code": "validation_error", "params": {"fields": ["name"]}}}


def test_missing_body_is_validation_error(logged: TestClient) -> None:
    reply = logged.post(f"{API}/folders", json={}, headers=H)
    assert reply.status_code == 422
    assert reply.json()["error"]["params"]["fields"] == ["name"]


def test_folder_patch_rejects_bad_name(logged: TestClient) -> None:
    folder = logged.post(f"{API}/folders", json={"name": "A"}, headers=H).json()
    reply = logged.patch(f"{API}/folders/{folder['id']}", json={"name": " "}, headers=H)
    assert reply.status_code == 422


def test_projects_crud(logged: TestClient) -> None:
    folder = logged.post(f"{API}/folders", json={"name": "F"}, headers=H).json()
    created = logged.post(
        f"{API}/projects", json={"name": "Todo app", "folder_id": folder["id"]}, headers=H
    )
    assert created.status_code == 201
    project = created.json()
    assert set(project) == {
        "id",
        "name",
        "folder_id",
        "created_at",
        "budget_usd",
        "status",
        "phase",
    }
    assert project["status"] == "active"
    assert project["budget_usd"] == "5.00"
    assert project["folder_id"] == folder["id"]

    loose = logged.post(f"{API}/projects", json={"name": "Loose"}, headers=H).json()
    assert loose["folder_id"] is None
    assert [p["name"] for p in logged.get(f"{API}/projects").json()] == ["Todo app", "Loose"]

    moved = logged.patch(
        f"{API}/projects/{loose['id']}", json={"folder_id": folder["id"]}, headers=H
    )
    assert moved.json()["folder_id"] == folder["id"]
    unfiled = logged.patch(f"{API}/projects/{loose['id']}", json={"folder_id": None}, headers=H)
    assert unfiled.json()["folder_id"] is None
    only_rename = logged.patch(
        f"{API}/projects/{project['id']}", json={"name": "Renamed"}, headers=H
    )
    assert only_rename.json()["name"] == "Renamed"
    assert only_rename.json()["folder_id"] == folder["id"], "absent folder_id must not unfile"

    assert logged.delete(f"{API}/projects/{project['id']}", headers=H).status_code == 204
    assert logged.delete(f"{API}/projects/{project['id']}", headers=H).status_code == 404


def test_deleting_folder_unfiles_its_projects(logged: TestClient) -> None:
    folder = logged.post(f"{API}/folders", json={"name": "F"}, headers=H).json()
    project = logged.post(
        f"{API}/projects", json={"name": "P", "folder_id": folder["id"]}, headers=H
    ).json()
    assert logged.delete(f"{API}/folders/{folder['id']}", headers=H).status_code == 204
    listing = logged.get(f"{API}/projects").json()
    assert [(p["id"], p["folder_id"]) for p in listing] == [(project["id"], None)]


def test_unknown_folder_and_bad_ids_are_404(logged: TestClient) -> None:
    ghost = str(uuid.uuid4())
    reply = logged.post(f"{API}/projects", json={"name": "P", "folder_id": ghost}, headers=H)
    assert reply.status_code == 404
    assert code(reply) == "not_found"
    project = logged.post(f"{API}/projects", json={"name": "P"}, headers=H).json()
    assert (
        logged.patch(
            f"{API}/projects/{project['id']}", json={"folder_id": ghost}, headers=H
        ).status_code
        == 404
    )
    assert logged.patch(f"{API}/folders/not-a-uuid", json={}, headers=H).status_code == 404
    assert logged.delete(f"{API}/projects/{ghost}", headers=H).status_code == 404


def test_lists_require_authentication(client: TestClient) -> None:
    for path in ("/folders", "/projects"):
        assert client.get(API + path).status_code == 401
    assert client.post(f"{API}/folders", json={"name": "x"}, headers=H).status_code == 401


def test_resources_are_scoped_to_their_owner(
    logged: TestClient, sessions: sessionmaker[Session]
) -> None:
    from cobble.auth.passwords import hash_password
    from cobble.auth.sessions import create_session
    from cobble.db import Folder, Project, User

    with sessions() as db:
        intruder = User(email="eve@example.com", password_hash=hash_password(PASSWORD))
        db.add(intruder)
        db.commit()
        eve_token = create_session(db, intruder.id)
    folder = logged.post(f"{API}/folders", json={"name": "Mine"}, headers=H).json()
    project = logged.post(
        f"{API}/projects", json={"name": "Mine", "folder_id": folder["id"]}, headers=H
    ).json()

    eve = TestClient(logged.app)
    eve.cookies.set("cobble_session", eve_token)
    assert eve.get(f"{API}/folders").json() == []
    assert eve.get(f"{API}/projects").json() == []
    assert (
        eve.patch(f"{API}/folders/{folder['id']}", json={"name": "X"}, headers=H).status_code == 404
    )
    assert eve.delete(f"{API}/folders/{folder['id']}", headers=H).status_code == 404
    assert (
        eve.patch(f"{API}/projects/{project['id']}", json={"name": "X"}, headers=H).status_code
        == 404
    )
    assert eve.delete(f"{API}/projects/{project['id']}", headers=H).status_code == 404
    assert (
        eve.post(
            f"{API}/projects", json={"name": "P", "folder_id": folder["id"]}, headers=H
        ).status_code
        == 404
    )
    own = eve.post(f"{API}/projects", json={"name": "Eve's"}, headers=H).json()
    assert (
        eve.patch(
            f"{API}/projects/{own['id']}", json={"folder_id": folder["id"]}, headers=H
        ).status_code
        == 404
    )
    with sessions() as db:
        assert len(db.scalars(select(Folder)).all()) == 1
        assert len(db.scalars(select(Project)).all()) == 2


def test_project_budget_can_be_changed_and_validated(logged: TestClient) -> None:
    created = logged.post(f"{API}/projects", json={"name": "P"}, headers=H).json()
    assert created["budget_usd"] == "5.00"
    url = f"{API}/projects/{created['id']}"

    changed = logged.patch(url, json={"budget_usd": "12.50"}, headers=H)
    assert changed.status_code == 200
    assert changed.json()["budget_usd"] == "12.50"

    unlimited = logged.patch(url, json={"budget_usd": None}, headers=H)
    assert unlimited.json()["budget_usd"] is None

    bad = logged.patch(url, json={"budget_usd": "-1"}, headers=H)
    assert bad.status_code == 422
    assert bad.json()["error"]["params"]["fields"] == ["budget_usd"]


def test_reset_link_changes_credentials_and_keeps_data(
    client: TestClient, sessions: sessionmaker[Session]
) -> None:
    assert activate(client, sessions).status_code == 201  # type: ignore[attr-defined]
    project = client.post(f"{API}/projects", json={"name": "Keep me"}, headers=H).json()

    with sessions() as db:
        user = db.scalars(select(User)).one()
        reset_token, _ = create_activation_token(db, user_id=user.id)
        db.execute(delete(AuthSession))  # what the CLI does
        db.commit()

    assert client.get(f"{API}/auth/me").status_code == 401  # old session is gone
    body = {"token": reset_token, "email": "new@example.com", "password": "a-new-password-1"}
    reply = client.post(f"{API}/auth/activate", json=body, headers=H)
    assert reply.status_code == 201
    assert reply.json()["email"] == "new@example.com"
    assert [p["id"] for p in client.get(f"{API}/projects").json()] == [project["id"]]

    again = client.post(f"{API}/auth/activate", json=body, headers=H)
    assert again.status_code == 409  # single use: now it is just an initialized instance

    client.post(f"{API}/auth/logout", headers=H)
    old = client.post(
        f"{API}/auth/login", json={"email": "admin@example.com", "password": PASSWORD}, headers=H
    )
    assert old.status_code == 401
    new = client.post(
        f"{API}/auth/login",
        json={"email": "new@example.com", "password": "a-new-password-1"},
        headers=H,
    )
    assert new.status_code == 200
