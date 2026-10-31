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
        },
        {
            "model": "cheap",
            "cost_usd": "0.00651235",
            "prompt_tokens": 211,
            "completion_tokens": 78,
            "calls": 5,
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
    assert first == len(statements) <= 4


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
