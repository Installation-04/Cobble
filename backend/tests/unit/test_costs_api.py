"""Costs API: aggregation over llm_calls joined to tasks (ADR 0007)."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.orm import Session, sessionmaker

from cobble import costs
from cobble.api.app import create_app
from cobble.auth.sessions import create_session
from cobble.config import Settings
from cobble.db import LLMCall, Plan, Project, Task, User
from cobble.db.models import PlatformState
from cobble.router.prices import Prices

from .scheduling import Harness, make_ready_project

API = "/api/v1"


def client_for(sessions: sessionmaker[Session], project_id: uuid.UUID | None) -> TestClient:
    app = create_app(
        {"database": lambda: None, "redis": lambda: None},
        settings=Settings(),
        session_factory=sessions,
        redis=object(),
    )
    client = TestClient(app)
    if project_id is not None:
        with sessions() as db:
            project = db.get(Project, project_id)
            assert project is not None
            client.cookies.set("cobble_session", create_session(db, project.owner_id))
    return client


def call(
    project: uuid.UUID,
    task: uuid.UUID | None,
    role: str | None,
    model: str,
    cost: str,
    prompt: int = 10,
    completion: int = 5,
) -> LLMCall:
    return LLMCall(
        project_id=project,
        task_id=task,
        role=role,
        model=model,
        cost_usd=Decimal(cost),
        prompt_tokens=prompt,
        completion_tokens=completion,
    )


@pytest.fixture
def pid(sessions: sessionmaker[Session]) -> uuid.UUID:
    return make_ready_project(sessions)


def task_ids(sessions: sessionmaker[Session], pid: uuid.UUID) -> dict[str, uuid.UUID]:
    Harness(sessions).start(pid)
    with sessions() as db:
        return {t.ref: t.id for t in db.query(Task).filter(Task.project_id == pid)}


def seed(sessions: sessionmaker[Session], pid: uuid.UUID) -> None:
    ids = task_ids(sessions, pid)
    other = make_ready_project(sessions)  # another project: must never leak in
    with sessions() as db:
        db.add_all(
            [
                call(pid, None, "planner", "strong", "0.10000000", 1000, 500),
                call(pid, None, "planner", "strong", "0.05000000", 200, 100),
                call(pid, ids["T-002"], "worker", "cheap", "0.00120000", 100, 50),
                call(pid, ids["T-002"], "test-writer", "cheap", "0.0003", 40, 20),
                call(pid, ids["T-002"], "worker", "strong", "0.02000000", 300, 30),
                call(pid, ids["T-010"], "worker", "cheap", "0.005", 70, 7),
                call(pid, ids["T-001"], "worker", "cheap", "0.00001234", 1, 1),
                call(pid, None, None, "cheap", "0.00000001", 0, 0),
                call(other, None, "planner", "strong", "9.99000000"),
            ]
        )
        db.commit()


def test_money_formatting() -> None:
    assert costs.money(None) == "0.00"
    assert costs.money(Decimal("0")) == "0.00"
    assert costs.money(Decimal("10")) == "10.00"
    assert costs.money(Decimal("0.3")) == "0.30"
    assert costs.money(Decimal("0.01234567")) == "0.01234567"
    assert costs.money(Decimal("0.123456789")) == "0.12345679"
    assert costs.money(0.30000000000000004) == "0.30"  # float noise from SQLite
    assert costs.money(Decimal("1234567.5")) == "1234567.50"


def test_project_costs_shape_and_numbers(sessions: sessionmaker[Session], pid: uuid.UUID) -> None:
    seed(sessions, pid)
    with sessions() as db:
        db.get(Project, pid).budget_usd = Decimal("5")  # type: ignore[union-attr]
        db.commit()
    body = client_for(sessions, pid).get(f"{API}/projects/{pid}/costs").json()
    assert set(body) == {
        "budget_usd",
        "spent_usd",
        "tokens",
        "estimate_usd",
        "by_task",
        "by_model",
        "by_role",
        "fallbacks",
        "free_calls",
        "price_changes",
        "savings",
    }
    assert body["budget_usd"] == "5.00"
    assert body["spent_usd"] == "0.17651235"
    assert body["tokens"] == {"prompt": 1711, "completion": 708}
    assert body["estimate_usd"] is None  # the test plan has an empty estimate

    def entry(ref: str | None, cost: str, prompt: int, completion: int, calls: int) -> dict:  # type: ignore[type-arg]
        return {
            "ref": ref,
            "cost_usd": cost,
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "calls": calls,
        }

    assert body["by_task"] == [
        entry("T-001", "0.00001234", 1, 1, 1),
        entry("T-002", "0.0215", 440, 100, 3),
        entry("T-010", "0.005", 70, 7, 1),
        entry(None, "0.15000001", 1200, 600, 3),  # planner calls and role-less calls
    ]
    assert body["by_model"] == [
        {
            "model": "strong",
            "cost_usd": "0.17",
            "prompt_tokens": 1500,
            "completion_tokens": 630,
            "calls": 3,
            "free": False,
        },
        {
            "model": "cheap",
            "cost_usd": "0.00651235",
            "prompt_tokens": 211,
            "completion_tokens": 78,
            "calls": 5,
            "free": False,
        },
    ]
    roles = {r["role"]: r for r in body["by_role"]}
    assert list(roles) == ["planner", "worker", "test-writer", None]
    assert roles["planner"]["cost_usd"] == "0.15" and roles["planner"]["calls"] == 2
    assert roles["worker"]["cost_usd"] == "0.02621234" and roles["worker"]["calls"] == 4
    assert roles["test-writer"]["cost_usd"] == "0.0003"
    assert roles[None]["cost_usd"] == "0.00000001"
    assert sum(Decimal(r["cost_usd"]) for r in body["by_task"]) == Decimal(body["spent_usd"])
    assert sum(Decimal(r["cost_usd"]) for r in body["by_role"]) == Decimal(body["spent_usd"])


def test_a_project_with_no_calls(sessions: sessionmaker[Session], pid: uuid.UUID) -> None:
    body = client_for(sessions, pid).get(f"{API}/projects/{pid}/costs").json()
    assert body == {
        "budget_usd": None,
        "spent_usd": "0.00",
        "tokens": {"prompt": 0, "completion": 0},
        "estimate_usd": None,
        "by_task": [],
        "by_model": [],
        "by_role": [],
        "fallbacks": {"calls": 0, "total_calls": 0, "by_model": []},
        "savings": None,
        "free_calls": 0,
        "price_changes": [],
    }


def test_calls_of_a_deleted_task_count_with_the_planner(
    sessions: sessionmaker[Session], pid: uuid.UUID
) -> None:
    with sessions() as db:
        db.add(call(pid, uuid.uuid4(), "worker", "cheap", "0.5"))
        db.commit()
    body = client_for(sessions, pid).get(f"{API}/projects/{pid}/costs").json()
    assert body["by_task"] == [
        {
            "ref": None,
            "cost_usd": "0.50",
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "calls": 1,
        }
    ]


def test_estimate_comes_from_the_approved_plan(
    sessions: sessionmaker[Session], pid: uuid.UUID
) -> None:
    with sessions() as db:
        approved = db.query(Plan).filter(Plan.project_id == pid).one()
        approved.estimate = {"tokens": 10, "cost_usd": "1.5"}
        db.add(Plan(project_id=pid, version=2, plan={}, estimate={"cost_usd": "9.00"}))
        db.commit()
    api = client_for(sessions, pid)
    assert api.get(f"{API}/projects/{pid}/costs").json()["estimate_usd"] == "1.50"
    with sessions() as db:
        db.query(Plan).filter(Plan.project_id == pid, Plan.version == 1).update({"status": "draft"})
        db.commit()
    assert api.get(f"{API}/projects/{pid}/costs").json()["estimate_usd"] == "9.00"


def test_costs_are_aggregated_in_a_fixed_number_of_queries(
    sessions: sessionmaker[Session], pid: uuid.UUID
) -> None:
    seed(sessions, pid)
    with sessions() as db:
        db.add_all(call(pid, None, "worker", f"m{n}", "0.01") for n in range(30))
        db.commit()
    api = client_for(sessions, pid)
    engine = sessions.kw["bind"]
    statements: list[str] = []

    def count(_c: object, _cur: object, statement: str, *_a: object) -> None:
        if "llm_calls" in statement or "FROM plans" in statement:
            statements.append(statement)

    event.listen(engine, "before_cursor_execute", count)
    try:
        assert api.get(f"{API}/projects/{pid}/costs").status_code == 200
        first = len(statements)
        with sessions() as db:
            db.add_all(call(pid, None, "worker", f"x{n}", "0.01") for n in range(30))
            db.commit()
        statements.clear()
        assert api.get(f"{API}/projects/{pid}/costs").status_code == 200
    finally:
        event.remove(engine, "before_cursor_execute", count)
    assert first == len(statements) <= 5  # tasks, models, roles, fallbacks, plan


def test_costs_need_login_and_ownership(sessions: sessionmaker[Session], pid: uuid.UUID) -> None:
    assert client_for(sessions, None).get(f"{API}/projects/{pid}/costs").status_code == 401
    stranger = client_for(sessions, make_ready_project(sessions))
    assert stranger.get(f"{API}/projects/{pid}/costs").status_code == 404
    assert stranger.get(f"{API}/projects/nope/costs").status_code == 404
    assert client_for(sessions, None).get(f"{API}/costs").status_code == 401


def test_global_costs_list_the_owners_projects(
    sessions: sessionmaker[Session], pid: uuid.UUID
) -> None:
    seed(sessions, pid)
    with sessions() as db:
        owner = db.get(Project, pid).owner_id  # type: ignore[union-attr]
        quiet = Project(owner_id=owner, name="Quiet", budget_usd=Decimal("2"), status="paused")
        db.add(quiet)
        db.commit()
        quiet_id = quiet.id
        assert db.get(User, owner) is not None
    rows = client_for(sessions, pid).get(f"{API}/costs").json()
    assert rows == [
        {
            "project_id": str(pid),
            "name": "My Todo App",
            "spent_usd": "0.17651235",
            "budget_usd": None,
            "status": "active",
        },
        {
            "project_id": str(quiet_id),
            "name": "Quiet",
            "spent_usd": "0.00",
            "budget_usd": "2.00",
            "status": "paused",
        },
    ]


def fell_back(project: uuid.UUID, model: str, failed: str, cost: str, n: int = 1) -> LLMCall:
    row = call(project, None, "worker", model, cost)
    row.fallback_from = failed
    row.fallbacks = n
    return row


def test_calls_answered_by_a_fallback_are_reported_with_who_answered_instead_of_whom(
    sessions: sessionmaker[Session], pid: uuid.UUID
) -> None:
    with sessions() as db:
        db.add_all(
            [
                call(pid, None, "worker", "local", "0"),  # answered by the first choice
                call(pid, None, "worker", "local", "0"),
                fell_back(pid, "cheap-api", "local", "0.01"),
                fell_back(pid, "cheap-api", "local", "0.02"),
                fell_back(pid, "strong-api", "local", "0.30", n=2),  # two models failed first
            ]
        )
        db.commit()
    body = client_for(sessions, pid).get(f"{API}/projects/{pid}/costs").json()
    assert body["fallbacks"]["calls"] == 3 and body["fallbacks"]["total_calls"] == 5
    entries = {e["model"]: e for e in body["fallbacks"]["by_model"]}
    assert entries["cheap-api"] == {
        "model": "cheap-api",
        "fallback_from": "local",
        "cost_usd": "0.03",
        "prompt_tokens": 20,
        "completion_tokens": 10,
        "calls": 2,
    }
    assert entries["strong-api"]["calls"] == 1 and entries["strong-api"]["cost_usd"] == "0.30"
    assert [e["model"] for e in body["fallbacks"]["by_model"]] == ["cheap-api", "strong-api"]


def test_no_fallback_means_an_empty_block(sessions: sessionmaker[Session], pid: uuid.UUID) -> None:
    with sessions() as db:
        db.add(call(pid, None, "worker", "local", "0"))
        db.commit()
    body = client_for(sessions, pid).get(f"{API}/projects/{pid}/costs").json()
    assert body["fallbacks"] == {"calls": 0, "total_calls": 1, "by_model": []}


# --- the savings counter -----------------------------------------------------------------------


class Book:
    """Stands in for the gateway's prices: {model: (prompt, completion)} in USD per token."""

    def __init__(self, prices: dict[str, tuple[str, str]]) -> None:
        self.prices_by_model = prices
        self.asked: list[str] = []

    def prices(self, model: str) -> Prices | None:
        self.asked.append(model)
        found = self.prices_by_model.get(model)
        return Prices(Decimal(found[0]), Decimal(found[1])) if found else None


def savings_for(
    sessions: sessionmaker[Session],
    pid: uuid.UUID,
    book: Book,
    *,
    routes: dict[str, list[str]] | None = None,
) -> dict | None:  # type: ignore[type-arg]
    api = client_for(sessions, pid)
    api.app.state.price_book = book  # type: ignore[attr-defined]
    if routes:
        with sessions() as db:
            db.add(PlatformState(id=1, role_routes=routes))
            db.commit()
    return api.get(f"{API}/projects/{pid}/costs").json()["savings"]  # type: ignore[no-any-return]


def test_the_counter_compares_the_real_cost_with_the_strongest_model(
    sessions: sessionmaker[Session], pid: uuid.UUID
) -> None:
    with sessions() as db:
        # 1,000 prompt + 500 completion tokens, really paid 0.002
        db.add(call(pid, None, "worker", "local", "0.002", prompt=1000, completion=500))
        db.commit()
    book = Book({"big": ("0.00001", "0.00003")})
    found = savings_for(sessions, pid, book, routes={"escalation": ["big", "other"]})
    # the same tokens with the strongest model: 1000 x 0.00001 + 500 x 0.00003 = 0.025
    assert found == {
        "reference_model": "big",
        "reference_cost_usd": "0.025",
        "actual_cost_usd": "0.002",
        "saved_usd": "0.023",
        "saved_percent": 92,
    }
    assert book.asked == ["big"]  # the first model of the escalation chain, nothing else


def test_a_project_that_cost_more_than_the_strongest_model_says_so(
    sessions: sessionmaker[Session], pid: uuid.UUID
) -> None:
    with sessions() as db:
        db.add(call(pid, None, "worker", "pricey", "1.00", prompt=100, completion=100))
        db.commit()
    found = savings_for(sessions, pid, Book({"fake": ("0.001", "0.001")}))
    assert found is not None and found["saved_usd"].startswith("-")
    assert found["saved_percent"] < 0  # shown as it is, never clamped to zero


def test_without_a_price_or_without_calls_there_is_no_figure(
    sessions: sessionmaker[Session], pid: uuid.UUID
) -> None:
    assert savings_for(sessions, pid, Book({"fake": ("1", "1")})) is None  # no calls yet
    with sessions() as db:
        db.add(call(pid, None, "worker", "local", "0.1"))
        db.commit()
    assert savings_for(sessions, pid, Book({})) is None  # the gateway cannot price the model


def test_the_default_model_is_the_reference_when_no_route_is_set(
    sessions: sessionmaker[Session], pid: uuid.UUID
) -> None:
    with sessions() as db:
        db.add(call(pid, None, "worker", "local", "0", prompt=10, completion=10))
        db.commit()
    book = Book({"fake": ("1", "1")})
    found = savings_for(sessions, pid, book)
    assert found is not None and found["reference_model"] == "fake"
    assert found["saved_usd"].startswith("20")  # 20 tokens x 1 - 0
