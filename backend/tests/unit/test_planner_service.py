from __future__ import annotations

import json
import uuid
from typing import Any

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from cobble.config import Settings
from cobble.db import Message, Plan, Project, Spec
from cobble.orchestrator.plan_schema import validate_plan
from cobble.orchestrator.service import PlannerService
from cobble.router.budget import BudgetExceeded
from cobble.router.gateway import GatewayError

from .fakes import FakeStreamRedis
from .planning import ScriptedLLM, events_of, load_script, make_project

SCRIPT = load_script()
VALID_PLAN = json.dumps(SCRIPT.valid_plan("en"))
INVALID_PLAN = json.dumps(SCRIPT.invalid_plan("en", 1))


def service(
    sessions: sessionmaker[Session], llm: ScriptedLLM, redis: FakeStreamRedis | None = None
) -> PlannerService:
    return PlannerService(sessions, llm, redis, Settings())  # type: ignore[arg-type]


def add_message(sessions: sessionmaker[Session], pid: uuid.UUID, role: str, content: str) -> str:
    with sessions() as db:
        message = Message(project_id=pid, role=role, content=content)
        db.add(message)
        db.commit()
        return str(message.id)


def add_spec(
    sessions: sessionmaker[Session], pid: uuid.UUID, status: str = "approved", version: int = 1
) -> None:
    with sessions() as db:
        db.add(Spec(project_id=pid, version=version, content="# Spec", status=status))
        db.commit()


def phase_of(sessions: sessionmaker[Session], pid: uuid.UUID) -> str:
    with sessions() as db:
        project = db.get(Project, pid)
        assert project is not None
        return project.phase


# --- interview -----------------------------------------------------------------------------


def test_reply_stores_the_answer_and_publishes_it(sessions: sessionmaker[Session]) -> None:
    pid = make_project(sessions)
    add_message(sessions, pid, "user", "I want a to-do app")
    redis = FakeStreamRedis()
    llm = ScriptedLLM("Who will use it?")
    assert service(sessions, llm, redis).run_job("reply", pid) is True

    with sessions() as db:
        rows = list(db.scalars(select(Message).order_by(Message.created_at)))
    assert [(m.role, m.content) for m in rows] == [
        ("user", "I want a to-do app"),
        ("assistant", "Who will use it?"),
    ]
    events = events_of(redis, pid)
    assert [name for name, _ in events] == ["job.started", "message.created"]
    assert events[0][1] == {"kind": "reply"}
    message = events[1][1]["message"]
    assert message["role"] == "assistant"
    assert message["content"] == "Who will use it?"
    assert phase_of(sessions, pid) == "interview"


def test_reply_prompt_contains_the_history_and_the_user_language(
    sessions: sessionmaker[Session],
) -> None:
    pid = make_project(sessions, lang="fr")
    add_message(sessions, pid, "user", "one")
    add_message(sessions, pid, "assistant", "two")
    add_message(sessions, pid, "user", "three")
    llm = ScriptedLLM("four")
    service(sessions, llm).reply(pid)
    messages = llm.calls[0]
    assert "French" in messages[0]["content"]
    assert [(m["role"], m["content"]) for m in messages[1:]] == [
        ("user", "one"),
        ("assistant", "two"),
        ("user", "three"),
    ]


def test_a_replayed_reply_job_does_not_answer_twice(sessions: sessionmaker[Session]) -> None:
    pid = make_project(sessions)
    first = add_message(sessions, pid, "user", "hello")
    llm = ScriptedLLM("hi", "again")
    svc = service(sessions, llm)
    svc.reply(pid, first)
    svc.reply(pid, first)  # the worker died before the ack: the job comes back
    assert len(llm.calls) == 1


def test_reply_for_an_older_message_is_skipped(sessions: sessionmaker[Session]) -> None:
    pid = make_project(sessions)
    old = add_message(sessions, pid, "user", "first")
    add_message(sessions, pid, "user", "second")
    llm = ScriptedLLM("x")
    service(sessions, llm).reply(pid, old)
    assert llm.calls == []


def test_reply_does_nothing_outside_the_interview_or_for_a_deleted_project(
    sessions: sessionmaker[Session],
) -> None:
    pid = make_project(sessions, phase="spec_review")
    add_message(sessions, pid, "user", "hello")
    llm = ScriptedLLM("x")
    svc = service(sessions, llm)
    svc.reply(pid)
    svc.reply(uuid.uuid4())
    assert llm.calls == []


# --- spec ----------------------------------------------------------------------------------


def test_generate_spec_creates_a_draft_and_moves_to_spec_review(
    sessions: sessionmaker[Session],
) -> None:
    pid = make_project(sessions)
    add_message(sessions, pid, "user", "a to-do app")
    redis = FakeStreamRedis()
    llm = ScriptedLLM("\n# Todo\n\n## Features\n- add\n")
    assert service(sessions, llm, redis).run_job("spec", pid) is True

    with sessions() as db:
        spec = db.scalars(select(Spec)).one()
    assert (spec.version, spec.status) == (1, "draft")
    assert spec.content == "# Todo\n\n## Features\n- add"
    assert phase_of(sessions, pid) == "spec_review"
    assert events_of(redis, pid) == [
        ("job.started", {"kind": "spec"}),
        ("spec.updated", {"version": 1}),
        ("phase.changed", {"phase": "spec_review"}),
    ]


def test_spec_feedback_makes_a_new_version_from_the_previous_one(
    sessions: sessionmaker[Session],
) -> None:
    pid = make_project(sessions)
    add_message(sessions, pid, "user", "a to-do app")
    redis = FakeStreamRedis()
    llm = ScriptedLLM("# V1", "# V2")
    svc = service(sessions, llm, redis)
    svc.generate_spec(pid)
    svc.generate_spec(pid, "add dark mode")

    with sessions() as db:
        versions = [(s.version, s.content) for s in db.scalars(select(Spec).order_by(Spec.version))]
    assert versions == [(1, "# V1"), (2, "# V2")]
    prompt = llm.calls[1][1]["content"]
    assert "# V1" in prompt
    assert "add dark mode" in prompt
    names = [name for name, _ in events_of(redis, pid)]
    assert names.count("phase.changed") == 1  # published once, on the first generation


def test_spec_generation_is_refused_after_the_plan_phase(sessions: sessionmaker[Session]) -> None:
    pid = make_project(sessions, phase="plan_review")
    llm = ScriptedLLM("# x")
    service(sessions, llm).generate_spec(pid)
    assert llm.calls == []


# --- plan ----------------------------------------------------------------------------------


def test_generate_plan_stores_plan_and_estimate_and_moves_to_plan_review(
    sessions: sessionmaker[Session],
) -> None:
    pid = make_project(sessions, phase="spec_review")
    add_spec(sessions, pid)
    redis = FakeStreamRedis()
    llm = ScriptedLLM(VALID_PLAN)
    assert service(sessions, llm, redis).run_job("plan", pid) is True

    with sessions() as db:
        row = db.scalars(select(Plan)).one()
    assert (row.version, row.status) == (1, "draft")
    assert len(validate_plan(row.plan).tasks) == 11
    assert row.estimate["tokens"] > 0
    assert row.estimate["cost_usd"].count(".") == 1
    assert [m["id"] for m in row.estimate["milestones"]] == ["M1", "M2", "M3"]
    assert phase_of(sessions, pid) == "plan_review"
    assert [n for n, _ in events_of(redis, pid)] == ["job.started", "plan.updated", "phase.changed"]
    assert "# Spec" in llm.calls[0][1]["content"]


def test_plan_needs_an_approved_spec(sessions: sessionmaker[Session]) -> None:
    pid = make_project(sessions, phase="spec_review")
    add_spec(sessions, pid, status="draft")
    llm = ScriptedLLM(VALID_PLAN)
    service(sessions, llm).generate_plan(pid)
    assert llm.calls == []
    with sessions() as db:
        assert db.scalars(select(Plan)).first() is None


def test_invalid_plan_is_retried_with_the_errors_then_accepted(
    sessions: sessionmaker[Session],
) -> None:
    pid = make_project(sessions, phase="spec_review")
    add_spec(sessions, pid)
    llm = ScriptedLLM("```json\n" + INVALID_PLAN + "\n```", VALID_PLAN)
    assert service(sessions, llm, FakeStreamRedis()).run_job("plan", pid) is True

    assert len(llm.calls) == 2
    retry = llm.calls[1]
    assert retry[-2]["role"] == "assistant"
    assert "tasks[2].acceptance" in retry[-1]["content"]
    assert "tasks[3].size" in retry[-1]["content"]
    with sessions() as db:
        assert db.scalars(select(Plan)).one().version == 1
    assert phase_of(sessions, pid) == "plan_review"


def test_text_that_is_not_json_is_retried_too(sessions: sessionmaker[Session]) -> None:
    pid = make_project(sessions, phase="spec_review")
    add_spec(sessions, pid)
    llm = ScriptedLLM("Sorry, here is a plan in prose.", VALID_PLAN)
    assert service(sessions, llm).run_job("plan", pid) is True
    assert "not valid JSON" in llm.calls[1][-1]["content"]


def test_exhausted_retries_fail_with_plan_invalid(sessions: sessionmaker[Session]) -> None:
    pid = make_project(sessions, phase="spec_review")
    add_spec(sessions, pid)
    redis = FakeStreamRedis()
    llm = ScriptedLLM(INVALID_PLAN, INVALID_PLAN, INVALID_PLAN, VALID_PLAN)
    assert service(sessions, llm, redis).run_job("plan", pid) is False

    assert len(llm.calls) == 3  # first try + 2 retries
    assert events_of(redis, pid)[-1] == ("job.failed", {"kind": "plan", "code": "plan_invalid"})
    assert phase_of(sessions, pid) == "spec_review"
    with sessions() as db:
        assert db.scalars(select(Plan)).first() is None


def test_plan_feedback_creates_version_two_from_the_previous_plan(
    sessions: sessionmaker[Session],
) -> None:
    pid = make_project(sessions, phase="spec_review")
    add_spec(sessions, pid)
    redis = FakeStreamRedis()
    llm = ScriptedLLM(VALID_PLAN, VALID_PLAN)
    svc = service(sessions, llm, redis)
    svc.generate_plan(pid)
    svc.generate_plan(pid, "split the web page task")

    with sessions() as db:
        assert [p.version for p in db.scalars(select(Plan).order_by(Plan.version))] == [1, 2]
    prompt = llm.calls[1][1]["content"]
    assert "Previous plan" in prompt
    assert "split the web page task" in prompt
    assert [n for n, _ in events_of(redis, pid)].count("phase.changed") == 1


# --- failures ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (BudgetExceeded(uuid.uuid4()), "budget_reached"),
        (GatewayError(500), "llm_error"),
        (httpx.ConnectError("refused"), "llm_error"),
        (RuntimeError("bug"), "internal_error"),
    ],
)
@pytest.mark.parametrize("kind", ["reply", "spec", "plan"])
def test_failures_become_job_failed_events(
    sessions: sessionmaker[Session], error: Exception, code: str, kind: str
) -> None:
    pid = make_project(sessions, phase="spec_review" if kind == "plan" else "interview")
    add_message(sessions, pid, "user", "hello")
    add_spec(sessions, pid)
    redis = FakeStreamRedis()
    assert service(sessions, ScriptedLLM(error), redis).run_job(kind, pid) is False
    assert events_of(redis, pid) == [
        ("job.started", {"kind": kind}),
        ("job.failed", {"kind": kind, "code": code}),
    ]


def test_unknown_job_kind_fails(sessions: sessionmaker[Session]) -> None:
    pid = make_project(sessions)
    assert service(sessions, ScriptedLLM(), FakeStreamRedis()).run_job("nope", pid) is False


def test_the_service_works_without_redis(sessions: sessionmaker[Session]) -> None:
    pid = make_project(sessions)
    add_message(sessions, pid, "user", "hello")
    assert service(sessions, ScriptedLLM("hi")).run_job("reply", pid) is True


def test_phase_flow_end_to_end_with_the_scripted_llm(sessions: sessionmaker[Session]) -> None:
    pid = make_project(sessions)
    add_message(sessions, pid, "user", "I want a to-do app")
    svc = service(sessions, ScriptedLLM("Who?", "# Spec", VALID_PLAN))
    svc.reply(pid)
    svc.generate_spec(pid)
    assert phase_of(sessions, pid) == "spec_review"
    with sessions() as db:
        spec = db.scalars(select(Spec)).one()
        spec.status = "approved"
        db.commit()
    svc.generate_plan(pid)
    assert phase_of(sessions, pid) == "plan_review"


def test_message_payload_is_json_serialisable(sessions: sessionmaker[Session]) -> None:
    pid = make_project(sessions)
    add_message(sessions, pid, "user", "hello")
    redis = FakeStreamRedis()
    service(sessions, ScriptedLLM("hi"), redis).reply(pid)
    payload: dict[str, Any] = events_of(redis, pid)[0][1]["message"]
    assert set(payload) == {"id", "role", "content", "created_at"}
