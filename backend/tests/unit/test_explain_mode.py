"""Explain mode (ADR 0017): the switch, the job, the stored summary and the report."""

from __future__ import annotations

import json
import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from cobble.capabilities.fakes_preview import FakePreviewProvider
from cobble.capabilities.llm import ChatResult, Role
from cobble.config import Settings
from cobble.db import Milestone, Project, User
from cobble.events import JOBS_STREAM
from cobble.orchestrator import prompts
from cobble.orchestrator.service import EXPLAIN_ROLE, PlannerService
from cobble.report import project_report, render_markdown
from cobble.router.policy import ROLES
from cobble.scheduler import demo
from cobble.worker import make_job_handler

from .fakes import FakeStreamRedis
from .planning import events_of
from .scheduling import Harness, make_ready_project
from .test_scheduler_demo import milestones, tick_until
from .test_tasks_api import API, H, client_for


class Teacher:
    """`LLMClient` recording each call (role, messages, project) and answering with a text."""

    def __init__(self, text: str = "You now have a page that lists your tasks.") -> None:
        self.text = text
        self.calls: list[tuple[Role, list[dict[str, Any]], uuid.UUID | None]] = []

    def chat(
        self,
        role: Role,
        messages: list[dict[str, Any]],
        *,
        project_id: uuid.UUID | None = None,
        task_id: uuid.UUID | None = None,
    ) -> ChatResult:
        self.calls.append((role, messages, project_id))
        return ChatResult(self.text, "fake", 1, 1, 0, None)  # type: ignore[arg-type]


@pytest.fixture
def redis() -> FakeStreamRedis:
    return FakeStreamRedis()


@pytest.fixture
def pid(sessions: sessionmaker[Session]) -> uuid.UUID:
    return make_ready_project(sessions)


@pytest.fixture
def h(sessions: sessionmaker[Session], redis: FakeStreamRedis) -> Harness:
    return Harness(sessions, preview=FakePreviewProvider(), redis=redis)


def set_mode(sessions: sessionmaker[Session], pid: uuid.UUID, on: bool, lang: str = "en") -> None:
    with sessions() as db:
        project = db.get(Project, pid)
        assert project is not None
        project.explain_mode = on
        user = db.get(User, project.owner_id)
        assert user is not None
        user.lang = lang
        db.commit()


def build_first(h: Harness, pid: uuid.UUID) -> None:
    h.start(pid)
    tick_until(h, pid, lambda: milestones(h, pid)["M1"].status == "built")


def explain_jobs(redis: FakeStreamRedis) -> list[dict[str, Any]]:
    jobs = [json.loads(e["job"]) for e in redis.entries(JOBS_STREAM)]
    return [j for j in jobs if j["kind"] == "explain"]


def service(
    sessions: sessionmaker[Session], llm: Teacher, redis: FakeStreamRedis
) -> PlannerService:
    return PlannerService(sessions, llm, redis, Settings())  # type: ignore[arg-type]


# --- the switch ---------------------------------------------------------------------------------


def test_the_mode_is_off_by_default_and_can_be_switched(
    sessions: sessionmaker[Session], redis: FakeStreamRedis, pid: uuid.UUID
) -> None:
    api = client_for(sessions, redis, pid)
    assert api.get(f"{API}/projects").json()[0]["explain_mode"] is False
    on = api.patch(f"{API}/projects/{pid}", json={"explain_mode": True}, headers=H)
    assert on.json()["explain_mode"] is True
    renamed = api.patch(f"{API}/projects/{pid}", json={"name": "Other"}, headers=H)
    assert renamed.json()["explain_mode"] is True, "an absent flag must not change it"
    off = api.patch(f"{API}/projects/{pid}", json={"explain_mode": False}, headers=H)
    assert off.json()["explain_mode"] is False
    created = api.post(f"{API}/projects", json={"name": "Learner", "explain_mode": True}, headers=H)
    assert created.json()["explain_mode"] is True


# --- when the job is queued ---------------------------------------------------------------------


def test_a_built_milestone_queues_one_explain_job_only_when_the_mode_is_on(
    sessions: sessionmaker[Session], h: Harness, redis: FakeStreamRedis, pid: uuid.UUID
) -> None:
    build_first(h, pid)
    assert explain_jobs(redis) == [], "off by default: no job, so no token spent"

    other = make_ready_project(sessions)
    set_mode(sessions, other, True)
    build_first(h, other)
    assert [j["ref"] for j in explain_jobs(redis)] == ["M1"]
    assert explain_jobs(redis)[0]["project_id"] == str(other)


def test_a_queue_outage_does_not_hold_the_build_back(
    sessions: sessionmaker[Session], pid: uuid.UUID
) -> None:
    set_mode(sessions, pid, True)
    broken = Harness(sessions, preview=FakePreviewProvider(), redis=FakeStreamRedis(fail=True))
    build_first(broken, pid)
    assert milestones(broken, pid)["M1"].status == "built"


# --- the job ------------------------------------------------------------------------------------


def test_the_summary_goes_through_the_reviewer_role_in_the_user_language(
    sessions: sessionmaker[Session], h: Harness, redis: FakeStreamRedis, pid: uuid.UUID
) -> None:
    set_mode(sessions, pid, True, lang="fr")
    build_first(h, pid)
    llm = Teacher("Vous pouvez maintenant voir vos tâches.")
    assert service(sessions, llm, redis).run_job("explain", pid, ref="M1")

    ((role, messages, project_id),) = llm.calls
    assert role is EXPLAIN_ROLE is Role.REVIEWER and role in ROLES
    assert project_id == pid, "accounted to the project"
    assert "French" in messages[0]["content"]
    assert "Milestone M1" in messages[1]["content"]
    assert milestones(h, pid)["M1"].explanation == "Vous pouvez maintenant voir vos tâches."
    name, payload = events_of(redis, pid)[-1]
    assert name == "milestone.updated" and payload["ref"] == "M1"


def test_a_replayed_job_costs_nothing_and_force_rewrites(
    sessions: sessionmaker[Session], h: Harness, redis: FakeStreamRedis, pid: uuid.UUID
) -> None:
    set_mode(sessions, pid, True)
    build_first(h, pid)
    llm = Teacher("first")
    planner = service(sessions, llm, redis)
    planner.run_job("explain", pid, ref="M1")
    planner.run_job("explain", pid, ref="M1")
    assert len(llm.calls) == 1
    llm.text = "second"
    planner.run_job("explain", pid, ref="M1", force=True)
    assert len(llm.calls) == 2 and milestones(h, pid)["M1"].explanation == "second"


@pytest.mark.parametrize("case", ["mode_off", "pending", "unknown_ref", "empty_answer"])
def test_nothing_is_stored_when_there_is_nothing_to_explain(
    case: str,
    sessions: sessionmaker[Session],
    h: Harness,
    redis: FakeStreamRedis,
    pid: uuid.UUID,
) -> None:
    set_mode(sessions, pid, case != "mode_off")
    ref = "M9" if case == "unknown_ref" else "M1"
    if case == "pending":
        h.start(pid)
    else:
        build_first(h, pid)
    llm = Teacher("   " if case == "empty_answer" else "text")
    ok = service(sessions, llm, redis).run_job("explain", pid, ref=ref)
    assert milestones(h, pid)["M1"].explanation is None
    if case == "empty_answer":
        assert not ok
        assert events_of(redis, pid)[-1][1]["code"] == "empty_explanation"
    else:
        assert ok and llm.calls == []


def test_reopening_a_milestone_drops_its_summary(
    sessions: sessionmaker[Session], h: Harness, redis: FakeStreamRedis, pid: uuid.UUID
) -> None:
    set_mode(sessions, pid, True)
    build_first(h, pid)
    service(sessions, Teacher(), redis).run_job("explain", pid, ref="M1")
    assert milestones(h, pid)["M1"].explanation
    with sessions() as db:
        project = db.get(Project, pid)
        assert project is not None
        demo.add_comment(db, demo.redis_emitter(redis), project, "M1", "Bigger font")
    assert milestones(h, pid)["M1"].explanation is None


def test_the_worker_hands_explain_jobs_to_the_planner(pid: uuid.UUID) -> None:
    seen: list[tuple[str, uuid.UUID, str | None, bool]] = []

    class Recorder:
        def run_job(
            self, kind: str, project_id: uuid.UUID, *, ref: str | None = None, force: bool = False
        ) -> bool:
            seen.append((kind, project_id, ref, force))
            return True

    handler = make_job_handler(Recorder())  # type: ignore[arg-type]
    job = {"kind": "explain", "project_id": str(pid), "ref": "M2", "force": True}
    handler({b"job": json.dumps(job).encode()})
    assert seen == [("explain", pid, "M2", True)]


def test_the_prompt_is_pure_and_bounded() -> None:
    tasks = [(f"Task {n}", ["it works"] * 9) for n in range(100)]
    one = prompts.explain_messages("Todo", ("M1", "Lists"), tasks, "en")
    assert one == prompts.explain_messages("Todo", ("M1", "Lists"), tasks, "en")
    body = one[1]["content"]
    assert body.count("\n- ") == prompts.EXPLAIN_MAX_TASKS
    assert body.count("* it works") == prompts.EXPLAIN_MAX_TASKS * 4
    assert "English" in one[0]["content"]
    assert "French" in prompts.explain_messages("Todo", ("M1", "Lists"), [], "fr")[0]["content"]


# --- the API ------------------------------------------------------------------------------------


def test_the_explain_endpoint_queues_a_forced_job_and_checks_the_state(
    sessions: sessionmaker[Session], h: Harness, redis: FakeStreamRedis, pid: uuid.UUID
) -> None:
    api: TestClient = client_for(sessions, redis, pid)
    url = f"{API}/projects/{pid}/milestones/M1/explain"
    h.start(pid)
    assert api.post(url, headers=H).json()["error"]["code"] == "explain_mode_off"
    set_mode(sessions, pid, True)
    assert api.post(url, headers=H).json()["error"]["code"] == "wrong_state"  # not built yet
    tick_until(h, pid, lambda: milestones(h, pid)["M1"].status == "built")
    before = len(explain_jobs(redis))
    assert api.post(url, headers=H).status_code == 202
    assert explain_jobs(redis)[before:] == [
        {"kind": "explain", "project_id": str(pid), "ref": "M1", "force": True}
    ]
    assert api.post(url.replace("M1", "M9"), headers=H).status_code == 404
    listed = api.get(f"{API}/projects/{pid}/milestones").json()
    assert listed[0]["explanation"] is None


# --- the report ---------------------------------------------------------------------------------


def test_the_report_carries_the_summaries_only_when_there_are_some(
    sessions: sessionmaker[Session], h: Harness, redis: FakeStreamRedis, pid: uuid.UUID
) -> None:
    set_mode(sessions, pid, True)
    build_first(h, pid)

    def report() -> dict[str, Any]:
        with sessions() as db:
            project = db.get(Project, pid)
            assert project is not None
            return project_report(db, project)

    assert report()["build"]["milestones"][0]["explanation"] is None
    assert "Explained in plain words" not in render_markdown(report(), "en")
    service(sessions, Teacher("A page lists your tasks."), redis).run_job("explain", pid, ref="M1")
    body = report()
    assert body["build"]["milestones"][0]["explanation"] == "A page lists your tasks."
    assert "## Explained in plain words" in render_markdown(body, "en")
    assert "## Expliqué en mots simples" in render_markdown(body, "fr")
    assert "A page lists your tasks." in render_markdown(body, "en")


def test_milestone_model_holds_the_summary(sessions: sessionmaker[Session], pid: uuid.UUID) -> None:
    with sessions() as db:
        db.add(Milestone(project_id=pid, ref="M7", title="x", explanation="e"))
        db.commit()
        row = db.query(Milestone).filter_by(project_id=pid, ref="M7").one()
        assert row.explanation == "e"
