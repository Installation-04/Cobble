"""End-of-project report (ADR 0014): JSON body, query count and the Markdown download."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from httpx import Response
from sqlalchemy import event
from sqlalchemy.orm import Session, sessionmaker

from cobble.db import Milestone, Project, Task, User
from cobble.db.models import PlatformState

from .scheduling import make_ready_project
from .test_costs_api import API, Book, call, client_for, seed


@pytest.fixture
def pid(sessions: sessionmaker[Session]) -> uuid.UUID:
    return make_ready_project(sessions)


def build(sessions: sessionmaker[Session], pid: uuid.UUID) -> None:
    """Tasks and spend of a finished-looking project: 11 tasks, one failed, one escalated."""
    seed(sessions, pid)
    start = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
    with sessions() as db:
        project = db.get(Project, pid)
        assert project is not None
        project.created_at = start
        project.phase = "done"
        project.budget_usd = Decimal("1")
        tasks = sorted(db.query(Task).filter(Task.project_id == pid), key=lambda t: t.ref)
        for index, task in enumerate(tasks):
            task.state = "failed" if index == 0 else "merged"
            task.escalated = index == 1
            task.attempts = 2 if index < 2 else 1
            task.updated_at = start + timedelta(hours=1, minutes=index)
        for m in db.query(Milestone).filter(Milestone.project_id == pid):
            m.status = "validated"
            m.validated_at = start + timedelta(hours=3, minutes=5)
        db.add(call(pid, None, "worker", "cheap", "0.5", 10, 10))
        db.commit()


def get(
    sessions: sessionmaker[Session], pid: uuid.UUID, query: str = "", book: Book | None = None
) -> Response:
    api = client_for(sessions, pid)
    if book is not None:
        api.app.state.price_book = book  # type: ignore[attr-defined]
    return api.get(f"{API}/projects/{pid}/report{query}")


def set_escalation(sessions: sessionmaker[Session], model: str) -> None:
    with sessions() as db:
        db.add(PlatformState(id=1, role_routes={"escalation": [model]}))
        db.commit()


def test_the_report_summarises_build_time_and_cost(
    sessions: sessionmaker[Session], pid: uuid.UUID
) -> None:
    build(sessions, pid)
    set_escalation(sessions, "big")
    res = get(sessions, pid, book=Book({"big": ("0.0001", "0.0001")}))
    assert res.status_code == 200
    body: dict[str, Any] = res.json()
    assert set(body) == {"project", "span", "build", "costs"}
    assert body["project"]["finished"] is True
    tasks = body["build"]["tasks"]
    assert tasks["total"] == 11 and tasks["failed"] == 1 and tasks["done"] == 10
    assert tasks["escalated"] == 1
    assert body["build"]["milestones_validated"] == len(body["build"]["milestones"]) == 3
    assert sum(m["tasks_total"] for m in body["build"]["milestones"]) == 11
    assert body["span"]["duration_seconds"] == 3 * 3600 + 5 * 60
    spend = body["costs"]
    assert spend["spent_usd"] == "0.67651235"
    assert spend["budget_used_percent"] == 68
    assert spend["estimate_usd"] is None and spend["estimate_delta_percent"] is None
    assert spend["savings"]["reference_model"] == "big"
    assert spend["by_model"] and spend["by_role"] and "fallbacks" in spend


def test_a_project_with_no_activity_still_has_a_report(
    sessions: sessionmaker[Session], pid: uuid.UUID
) -> None:
    body = get(sessions, pid).json()
    assert body["build"]["tasks"]["total"] == 0
    assert body["build"]["milestones"] == []
    assert body["costs"]["spent_usd"] == "0.00"
    assert body["costs"]["savings"] is None
    assert body["project"]["finished"] is False


def test_the_report_uses_a_fixed_number_of_queries(
    sessions: sessionmaker[Session], pid: uuid.UUID
) -> None:
    build(sessions, pid)
    engine = sessions.kw["bind"]
    statements: list[str] = []

    def count(_c: object, _cur: object, statement: str, *_a: object) -> None:
        if statement.lstrip().upper().startswith("SELECT") and any(
            name in statement for name in ("llm_calls", "plans", "tasks", "milestones")
        ):
            statements.append(statement)

    event.listen(engine, "before_cursor_execute", count)
    try:
        assert get(sessions, pid).status_code == 200
        first = len(statements)
        with sessions() as db:
            db.add_all(call(pid, None, "worker", f"m{n}", "0.01") for n in range(30))
            db.add_all(
                Task(
                    project_id=pid,
                    ref=f"C-{n:03d}",
                    title="x",
                    milestone="M1",
                    tests="t",
                    size="S",
                    role="worker",
                    kind="comment",
                )
                for n in range(30)
            )
            db.commit()
        statements.clear()
        assert get(sessions, pid).status_code == 200
    finally:
        event.remove(engine, "before_cursor_execute", count)
    # tasks, milestones, the four of the spend (tasks, models, roles, fallbacks) and the plan
    assert first == len(statements) <= 8


def test_the_report_needs_login_and_ownership(
    sessions: sessionmaker[Session], pid: uuid.UUID
) -> None:
    assert client_for(sessions, None).get(f"{API}/projects/{pid}/report").status_code == 401
    other = make_ready_project(sessions)
    assert client_for(sessions, other).get(f"{API}/projects/{pid}/report").status_code == 404


def test_the_markdown_comes_in_english_by_default_and_downloads(
    sessions: sessionmaker[Session], pid: uuid.UUID
) -> None:
    build(sessions, pid)
    res = get(sessions, pid, "?format=md", Book({}))
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/markdown")
    disposition = res.headers["content-disposition"]
    assert 'attachment; filename="cobble-report-my-todo-app.md"' in disposition
    text = res.text
    assert text.startswith("# Project report: My Todo App")
    for heading in ("What was built", "Time span", "Costs", "Savings", "Cost per model"):
        assert f"## {heading}" in text
    assert "## Fallbacks" in text
    assert "3 of 3 milestones validated" in text
    assert "3 h 5 min" in text
    assert "$0.67651235" in text


def test_the_markdown_follows_the_language_of_the_user(
    sessions: sessionmaker[Session], pid: uuid.UUID
) -> None:
    build(sessions, pid)
    set_escalation(sessions, "big")
    with sessions() as db:
        project = db.get(Project, pid)
        assert project is not None
        user = db.get(User, project.owner_id)
        assert user is not None
        user.lang = "fr"
        db.commit()
    text = get(sessions, pid, "?format=md", Book({"big": ("0.01", "0.01")})).text
    assert text.startswith("# Rapport de projet : My Todo App")
    assert "## Ce qui a été construit" in text
    assert "3 jalons validés sur 3" in text
    assert "## Économies" in text
    assert "Vous avez économisé" in text
    assert "Project report" not in text and "What was built" not in text


def test_a_loss_is_written_as_a_loss_and_pipes_do_not_break_tables(
    sessions: sessionmaker[Session], pid: uuid.UUID
) -> None:
    with sessions() as db:
        db.add(call(pid, None, "worker", "a|b", "10", 10, 10))
        db.commit()
    set_escalation(sessions, "big")
    text = get(sessions, pid, "?format=md", Book({"big": ("0.0001", "0.0001")})).text
    assert "No saving compared with big." in text
    assert "a\\|b" in text


def test_an_unknown_format_is_refused(sessions: sessionmaker[Session], pid: uuid.UUID) -> None:
    assert get(sessions, pid, "?format=pdf").status_code == 422
