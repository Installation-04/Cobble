"""End to end: interview -> spec -> plan through the API, the job queue and the model gateway.

Needs Postgres, Redis and an OpenAI-compatible endpoint serving the fake-llm cassettes:
  COBBLE_TEST_DATABASE_URL, COBBLE_TEST_REDIS_URL, COBBLE_TEST_LITELLM_URL
  (COBBLE_TEST_LITELLM_KEY if the endpoint needs one). The URL may be LiteLLM wired to the
  fake provider, or the fake-llm server itself: both speak /v1/chat/completions.
The test deletes the `cobble:jobs` stream first: use a Redis that is not shared with a live stack.
"""

from __future__ import annotations

import importlib.util
import json
import os
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from redis import Redis
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from cobble.api.app import create_app
from cobble.auth.sessions import create_session
from cobble.config import Settings
from cobble.db import LLMCall, Plan, Project, Spec, User, make_engine, make_session_factory
from cobble.events import JOBS_STREAM, project_stream
from cobble.orchestrator.plan_schema import SCHEMA_PATH, validate_plan
from cobble.worker import build_planner, consume_jobs_once, ensure_jobs_group, make_job_handler

from .conftest import BACKEND, require

pytestmark = pytest.mark.integration

H = {"X-Requested-With": "cobble"}
API = "/api/v1"
SCRIPT = BACKEND.parent / "providers" / "fake-llm" / "scripts" / "make_todo_cassettes.py"


def load_script() -> Any:
    spec = importlib.util.spec_from_file_location("make_todo_cassettes", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


script = load_script()


class Stack:
    def __init__(self, database_url: str, redis_url: str, litellm_url: str, lang: str) -> None:
        self.lang = lang
        self.settings = Settings(
            database_url=database_url,
            redis_url=redis_url,
            litellm_url=litellm_url,
            litellm_key=os.environ.get("COBBLE_TEST_LITELLM_KEY", ""),
            default_model="fake",
        )
        self.sessions: sessionmaker[Session] = make_session_factory(make_engine(database_url))
        self.redis = Redis.from_url(redis_url)
        self.redis.delete(JOBS_STREAM)
        ensure_jobs_group(self.redis)
        self.handler = make_job_handler(build_planner(self.settings, self.redis))
        self.api = TestClient(
            create_app(settings=self.settings, session_factory=self.sessions, redis=self.redis)
        )
        with self.sessions() as db:
            user = User(email=f"{uuid.uuid4().hex[:10]}@example.com", password_hash="x", lang=lang)
            db.add(user)
            db.commit()
            self.user_id = user.id
            self.api.cookies.set("cobble_session", create_session(db, user.id))

    def drain(self) -> int:
        """Run every queued job, like the worker would."""
        total = 0
        while (done := consume_jobs_once(self.redis, "test", self.handler, block_ms=50)) > 0:
            total += done
        return total

    def post(self, path: str, body: dict[str, Any] | None = None) -> Any:
        return self.api.post(f"{API}{path}", json=body or {}, headers=H)

    def project(self) -> str:
        reply = self.post("/projects", {"name": f"todo-{uuid.uuid4().hex[:6]}"})
        assert reply.status_code == 201
        return str(reply.json()["id"])

    def event_names(self, pid: str) -> list[str]:
        entries = self.redis.xrange(project_stream(pid))
        return [fields[b"type"].decode() for _id, fields in entries]

    def phase(self, pid: str) -> str:
        return str(
            next(p for p in self.api.get(f"{API}/projects").json() if p["id"] == pid)["phase"]
        )


@pytest.fixture(params=["en", "fr"])
def stack(
    migrated_database: str, redis_url: str, request: pytest.FixtureRequest
) -> Iterator[Stack]:
    litellm_url = require("COBBLE_TEST_LITELLM_URL")
    yield Stack(migrated_database, redis_url, litellm_url, request.param)


def test_reference_todo_project_yields_a_valid_spec_and_plan(stack: Stack) -> None:
    lang = stack.lang
    first, second = script.USER_MESSAGES[lang]
    reply1, reply2 = script.ASSISTANT_REPLIES[lang]
    pid = stack.project()
    assert stack.phase(pid) == "interview"

    # Interview, two turns.
    assert stack.post(f"/projects/{pid}/messages", {"content": first}).status_code == 202
    assert stack.drain() == 1
    assert stack.post(f"/projects/{pid}/messages", {"content": second}).status_code == 202
    assert stack.drain() == 1
    chat = stack.api.get(f"{API}/projects/{pid}/messages").json()
    assert [(m["role"], m["content"]) for m in chat] == [
        ("user", first),
        ("assistant", reply1),
        ("user", second),
        ("assistant", reply2),
    ]

    # Spec.
    assert stack.post(f"/projects/{pid}/spec/generate").status_code == 202
    assert stack.drain() == 1
    spec = stack.api.get(f"{API}/projects/{pid}/spec").json()
    assert spec["version"] == 1
    assert spec["status"] == "draft"
    assert spec["content"] == script.SPECS[lang].strip()
    for section in ("##",):
        assert section in spec["content"]
    assert stack.phase(pid) == "spec_review"
    assert stack.post(f"/projects/{pid}/spec/approve").json()["status"] == "approved"

    # Plan.
    assert stack.post(f"/projects/{pid}/plan/generate").status_code == 202
    assert stack.drain() == 1
    plan = stack.api.get(f"{API}/projects/{pid}/plan").json()
    parsed = validate_plan(plan["plan"])  # the strict schema (also exported as JSON Schema)
    assert plan["plan"] == script.valid_plan(lang)
    assert len(parsed.milestones) <= 3
    assert all(task.acceptance and task.size in ("S", "M") for task in parsed.tasks)
    assert plan["estimate"]["tokens"] > 0
    assert {m["id"] for m in plan["estimate"]["milestones"]} == {"M1", "M2", "M3"}
    assert stack.phase(pid) == "plan_review"
    assert json.loads(SCHEMA_PATH.read_text("utf-8"))["required"] == ["milestones", "tasks"]

    # Approval.
    approved = stack.post(f"/projects/{pid}/plan/approve")
    assert approved.status_code == 200
    assert stack.phase(pid) == "ready"

    # Every call was recorded by the cost router with the planner role.
    with stack.sessions() as db:
        calls = list(db.scalars(select(LLMCall).where(LLMCall.project_id == uuid.UUID(pid))))
    assert len(calls) == 4
    assert {c.role for c in calls} == {"planner"}
    assert all(c.prompt_tokens > 0 and c.completion_tokens > 0 for c in calls)

    names = stack.event_names(pid)
    for expected in (
        "message.created",
        "job.started",
        "spec.updated",
        "plan.updated",
        "phase.changed",
    ):
        assert expected in names
    assert "job.failed" not in names


def seed_approved_spec(stack: Stack, scenario: str) -> str:
    pid = stack.project()
    with stack.sessions() as db:
        project = db.get(Project, uuid.UUID(pid))
        assert project is not None
        project.phase = "spec_review"
        db.add(
            Spec(
                project_id=project.id,
                version=1,
                content=script.retry_spec(scenario),
                status="approved",
            )
        )
        db.commit()
    return pid


def test_invalid_plan_is_retried_with_the_errors_and_then_accepted(stack: Stack) -> None:
    pid = seed_approved_spec(stack, "retry")
    assert stack.post(f"/projects/{pid}/plan/generate").status_code == 202
    assert stack.drain() == 1

    plan = stack.api.get(f"{API}/projects/{pid}/plan").json()
    validate_plan(plan["plan"])
    assert plan["version"] == 1
    with stack.sessions() as db:
        calls = list(db.scalars(select(LLMCall).where(LLMCall.project_id == uuid.UUID(pid))))
    assert len(calls) == 2  # the invalid plan, then the corrected one
    assert "job.failed" not in stack.event_names(pid)
    assert stack.phase(pid) == "plan_review"


def test_a_plan_that_stays_invalid_is_rejected_end_to_end(stack: Stack) -> None:
    pid = seed_approved_spec(stack, "exhausted")
    assert stack.post(f"/projects/{pid}/plan/generate").status_code == 202
    assert stack.drain() == 1

    assert stack.api.get(f"{API}/projects/{pid}/plan").status_code == 404
    with stack.sessions() as db:
        assert db.scalars(select(Plan).where(Plan.project_id == uuid.UUID(pid))).first() is None
        calls = list(db.scalars(select(LLMCall).where(LLMCall.project_id == uuid.UUID(pid))))
    assert len(calls) == 3  # first try + 2 retries
    failed = [
        json.loads(fields[b"payload"])
        for _id, fields in stack.redis.xrange(project_stream(pid))
        if fields[b"type"] == b"job.failed"
    ]
    assert failed == [{"kind": "plan", "code": "plan_invalid"}]
    assert stack.phase(pid) == "spec_review"
    # The job was acknowledged: nothing is left to retry.
    assert stack.drain() == 0


def test_the_budget_stops_the_planner(stack: Stack) -> None:
    pid = stack.project()
    with stack.sessions() as db:
        project = db.get(Project, uuid.UUID(pid))
        assert project is not None
        project.status = "paused"
        db.add(
            Spec(
                project_id=project.id,
                version=1,
                content=script.retry_spec("retry"),
                status="approved",
            )
        )
        project.phase = "spec_review"
        db.commit()
    # The API refuses while paused; a job queued before the pause fails with budget_reached.
    assert stack.post(f"/projects/{pid}/plan/generate").status_code == 409
    from cobble.events import enqueue_job

    enqueue_job(stack.redis, "plan", pid)
    assert stack.drain() == 1
    assert "budget_reached" in [
        json.loads(fields[b"payload"]).get("code")
        for _id, fields in stack.redis.xrange(project_stream(pid))
        if fields[b"type"] == b"job.failed"
    ]
