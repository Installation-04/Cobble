"""Lessons learned (ADR 0026): signals, redaction, dedupe and cap, prompts, scheduler hooks, API."""

from __future__ import annotations

import uuid
from dataclasses import replace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from cobble.capabilities.agent import AgentOutcome
from cobble.capabilities.ci import CIState
from cobble.capabilities.fakes import FakeAgentRunner
from cobble.db import Project, ProjectLesson, User
from cobble.scheduler import lessons

from .fakes import FakeStreamRedis
from .scheduling import Harness, make_ready_project, script
from .test_planning_api import API, H, client_for, owner_of

PYTEST_LOG = """\
============ short test summary info ============
FAILED tests/test_todos.py::test_create_todo - AssertionError: assert 201 == 422
FAILED tests/test_todos.py::test_other - KeyError: 'x'
"""


@pytest.fixture
def pid(sessions: sessionmaker[Session]) -> uuid.UUID:
    return make_ready_project(sessions)


def texts(sessions: sessionmaker[Session], pid: uuid.UUID) -> list[str]:
    with sessions() as db:
        rows = db.scalars(select(ProjectLesson).where(ProjectLesson.project_id == pid))
        return sorted(r.text for r in rows)


# --- signals and redaction ----------------------------------------------------------------


def test_ci_signal_is_the_first_failing_test_and_its_message() -> None:
    text = lessons.signal_from_ci(PYTEST_LOG)
    assert text is not None
    assert "tests/test_todos.py::test_create_todo" in text
    assert "assert 201 == 422" in text
    assert "test_other" not in text


def test_ci_signal_reads_the_assertion_line_when_the_summary_has_none() -> None:
    log = "FAILED tests/test_a.py::test_x\n    def test_x():\nE   assert 1 == 2\n"
    text = lessons.signal_from_ci(log)
    assert text is not None and "assert 1 == 2" in text


def test_ci_signal_reads_a_vitest_failure() -> None:
    text = lessons.signal_from_ci(" FAIL  src/App.test.tsx > shows todos\nAssertionError: boom\n")
    assert text is not None and "src/App.test.tsx > shows todos" in text and "boom" in text


@pytest.mark.parametrize("detail", ["", "CI did not finish in time", "merge refused: stale"])
def test_ci_without_a_test_signal_teaches_nothing(detail: str) -> None:
    assert lessons.signal_from_ci(detail) is None


def test_loop_signal_is_the_repeated_line() -> None:
    log = "ok\npip install foo\nerror: nope\npip install foo\npip install foo\n"
    text = lessons.signal_from_loop(log)
    assert text is not None and "pip install foo" in text and "repeating" in text
    assert lessons.signal_from_loop("") is None
    assert "last output" in (lessons.signal_from_loop("one\ntwo") or "")


def test_timeout_signal_is_the_last_line() -> None:
    text = lessons.signal_from_timeout("start\nrunning the whole suite\n")
    assert text is not None and "running the whole suite" in text
    assert lessons.signal_from_timeout("  \n") is None


def test_secrets_are_redacted_and_text_is_capped() -> None:
    secret = "ghp_" + "A1b2C3d4" * 4
    dirty = (
        f"FAILED tests/t.py::test_a - AssertionError: token={secret} "
        "url https://bob:hunter2@git.local/x Authorization: Bearer abcdefghijkl1234 " + "x" * 600
    )
    text = lessons.signal_from_ci(dirty)
    assert text is not None
    for leaked in (secret, "hunter2", "abcdefghijkl1234"):
        assert leaked not in text
    assert len(text) <= lessons.MAX_TEXT
    assert "***" in text


def test_a_long_test_name_is_not_taken_for_a_secret() -> None:
    name = "test_creating_a_todo_with_an_empty_title_is_rejected"
    assert name in lessons.redact(name)


# --- storage: dedupe, cap, injection --------------------------------------------------------


def test_the_same_lesson_gains_a_hit_instead_of_a_copy(
    sessions: sessionmaker[Session], pid: uuid.UUID
) -> None:
    with sessions() as db:
        first = lessons.record(db, pid, "CI failed on a: assert 1 == 2", lessons.CI_FAILURE, "T-1")
        again = lessons.record(db, pid, "ci failed on a:  assert 7 == 9", lessons.CI_FAILURE, "T-2")
        db.commit()
        assert first is not None and again is not None and first.id == again.id
        assert again.hits == 2
        assert db.scalars(select(ProjectLesson)).all() == [first]


def test_over_the_cap_the_least_hit_oldest_lesson_is_dropped(
    sessions: sessionmaker[Session], pid: uuid.UUID
) -> None:
    with sessions() as db:
        for i in range(lessons.MAX_ACTIVE):
            lessons.record(db, pid, f"lesson number {'x' * i}", lessons.LOOP)
        db.commit()
        hot = lessons.record(db, pid, "lesson number ", lessons.LOOP)  # first one, now 2 hits
        assert hot is not None and hot.hits == 2
        lessons.record(db, pid, "brand new lesson", lessons.TIMEOUT)
        db.commit()
        kept = {r.text for r in db.scalars(select(ProjectLesson))}
    assert len(kept) == lessons.MAX_ACTIVE
    assert "brand new lesson" in kept and "lesson number" in kept
    assert "lesson number x" not in kept  # oldest of the single-hit ones


def test_manual_lessons_are_never_dropped(sessions: sessionmaker[Session], pid: uuid.UUID) -> None:
    with sessions() as db:
        for i in range(lessons.MAX_ACTIVE):
            lessons.record(db, pid, f"mine {'y' * i}", lessons.MANUAL)
        assert lessons.record(db, pid, "captured", lessons.CI_FAILURE) is None
        db.commit()
        assert db.scalars(select(ProjectLesson)).all().__len__() == lessons.MAX_ACTIVE


def test_prompt_block_is_empty_without_lessons_and_bounded_with_them(
    sessions: sessionmaker[Session], pid: uuid.UUID
) -> None:
    with sessions() as db:
        assert lessons.prompt_block(db, pid) == ""
        for i in range(12):
            lessons.record(db, pid, f"{i}: " + "z" * 290, lessons.LOOP)
        db.commit()
        block = lessons.prompt_block(db, pid)
        assert block.startswith("\nLessons from this project")
        assert block.count("\n- ") <= lessons.INJECT_MAX
        assert len(block) <= lessons.INJECT_CHARS + 200
        for row in db.scalars(select(ProjectLesson)):
            row.active = False
        db.commit()
        assert lessons.prompt_block(db, pid) == ""


def test_prompt_block_prefers_hits_then_recency(
    sessions: sessionmaker[Session], pid: uuid.UUID
) -> None:
    with sessions() as db:
        for i in range(7):
            lessons.record(db, pid, f"lesson {chr(97 + i)}", lessons.LOOP)
        lessons.record(db, pid, "lesson a", lessons.LOOP)  # a second hit
        db.commit()
        shown = [r.text for r in lessons.injected(db, pid)]
    assert len(shown) == lessons.INJECT_MAX and shown[0] == "lesson a"


# --- scheduler ---------------------------------------------------------------------------


def test_a_task_failing_twice_in_ci_teaches_the_next_tasks(
    sessions: sessionmaker[Session], pid: uuid.UUID
) -> None:
    h = Harness(sessions)
    h.start(pid)
    repo = h.repo_ref(pid)
    log = "FAILED tests/test_health.py::test_ok - AssertionError: assert 1 == 2"
    h.ci.set_result(repo, "task/t-001@1", CIState.FAILURE, log)
    h.ci.set_result(repo, "task/t-001@2", CIState.FAILURE, log)
    h.run_until(pid)
    stored = texts(sessions, pid)
    assert len(stored) == 1 and "test_health.py::test_ok" in stored[0]
    with sessions() as db:
        row = db.scalars(select(ProjectLesson)).one()
        assert (row.source, row.task_ref, row.hits) == ("ci_failure", "T-001", 1)
    marked = [t for t in h.agents.runs if "Lessons from this project" in t.instructions]
    assert marked and all("T-001:worker:1]" not in t.marker for t in marked)
    assert any(t.marker.startswith("[cobble-task:T-002:test-writer") for t in marked)
    assert all(t.instructions.startswith("[cobble-task:") for t in marked)  # marker stays first


def test_one_failed_attempt_is_not_a_lesson(
    sessions: sessionmaker[Session], pid: uuid.UUID
) -> None:
    h = Harness(sessions)
    h.start(pid)
    h.ci.set_result(
        h.repo_ref(pid), "task/t-001@1", CIState.FAILURE, "FAILED tests/a.py::t - Error: x"
    )
    h.run_until(pid)
    assert texts(sessions, pid) == []
    assert not any("Lessons from this project" in t.instructions for t in h.agents.runs)


def test_a_repeated_loop_is_captured(sessions: sessionmaker[Session], pid: uuid.UUID) -> None:
    class Looping(FakeAgentRunner):
        def start(self, task: Any) -> str:
            run_id = super().start(task)
            if self.script.get(("T-001", "worker", 1)) or "T-001:worker" in task.marker:
                self._results[run_id] = replace(self._results[run_id], log="retry\nretry\nretry\n")
            return run_id

    agents = Looping(
        script=script(
            ("T-001", "worker", 1, AgentOutcome.LOOP_DETECTED),
            ("T-001", "worker", 2, AgentOutcome.LOOP_DETECTED),
        )
    )
    h = Harness(sessions, agents=agents)
    h.start(pid)
    h.run_until(pid)
    (only,) = texts(sessions, pid)
    assert "repeating: retry" in only


def test_a_failing_capture_never_breaks_the_scheduler(
    sessions: sessionmaker[Session], pid: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*_a: Any, **_k: Any) -> Any:
        raise RuntimeError("nope")

    monkeypatch.setattr(lessons, "record", boom)
    h = Harness(sessions)
    h.start(pid)
    log = "FAILED tests/a.py::t - Error: x"
    h.ci.set_result(h.repo_ref(pid), "task/t-001@1", CIState.FAILURE, log)
    h.ci.set_result(h.repo_ref(pid), "task/t-001@2", CIState.FAILURE, log)
    h.run_until(pid)
    assert h.tasks(pid)["T-001"].state == "merged"


# --- API ---------------------------------------------------------------------------------


@pytest.fixture
def api(sessions: sessionmaker[Session], pid: uuid.UUID) -> TestClient:
    return client_for(sessions, FakeStreamRedis(), owner_of(sessions, pid))


def url(pid: uuid.UUID, suffix: str = "") -> str:
    return f"{API}/projects/{pid}/lessons{suffix}"


def test_the_owner_adds_edits_disables_and_deletes_lessons(api: TestClient, pid: uuid.UUID) -> None:
    assert api.get(url(pid)).json() == []
    created = api.post(url(pid), json={"text": "  Use uv, not pip  "}, headers=H)
    assert created.status_code == 201
    body = created.json()
    assert (body["text"], body["source"], body["active"], body["injected"]) == (
        "Use uv, not pip",
        "manual",
        True,
        True,
    )
    lid = body["id"]

    edited = api.patch(url(pid, f"/{lid}"), json={"text": "Always use uv"}, headers=H)
    assert edited.json()["text"] == "Always use uv"
    off = api.patch(url(pid, f"/{lid}"), json={"active": False}, headers=H).json()
    assert (off["active"], off["injected"]) == (False, False)
    assert [x["id"] for x in api.get(url(pid)).json()] == [lid]

    assert api.delete(url(pid, f"/{lid}"), headers=H).status_code == 204
    assert api.get(url(pid)).json() == []
    assert api.delete(url(pid, f"/{lid}"), headers=H).status_code == 404


def test_validation_and_the_cap(api: TestClient, pid: uuid.UUID) -> None:
    for bad in ("", "   ", "x" * 301):
        reply = api.post(url(pid), json={"text": bad}, headers=H)
        assert reply.status_code == 422
    for i in range(lessons.MAX_ACTIVE):
        assert (
            api.post(url(pid), json={"text": f"rule {chr(97 + i)}"}, headers=H).status_code == 201
        )
    full = api.post(url(pid), json={"text": "one too many"}, headers=H)
    assert full.status_code == 409 and full.json()["error"]["code"] == "lessons_full"


def test_enabling_over_the_cap_is_refused(
    sessions: sessionmaker[Session], api: TestClient, pid: uuid.UUID
) -> None:
    with sessions() as db:
        off = lessons.record(db, pid, "disabled one", lessons.CI_FAILURE)
        assert off is not None
        off.active = False
        for i in range(lessons.MAX_ACTIVE):
            lessons.record(db, pid, f"rule {chr(97 + i)}", lessons.MANUAL)
        db.commit()
        off_id = off.id
    reply = api.patch(url(pid, f"/{off_id}"), json={"active": True}, headers=H)
    assert reply.status_code == 409


def test_csrf_header_is_required(api: TestClient, pid: uuid.UUID) -> None:
    assert api.post(url(pid), json={"text": "x"}).status_code in (400, 403)


def test_lessons_are_private_to_the_project_owner(
    sessions: sessionmaker[Session], redis: Any = None
) -> None:
    mine = make_ready_project(sessions)
    other = make_ready_project(sessions)
    with sessions() as db:
        lessons.record(db, other, "not yours", lessons.MANUAL)
        row = db.scalars(select(ProjectLesson)).one()
        db.commit()
        row_id = row.id
    client = client_for(sessions, FakeStreamRedis(), owner_of(sessions, mine))
    assert client.get(url(other)).status_code == 404
    assert client.get(url(mine)).json() == []
    assert (
        client.patch(url(mine, f"/{row_id}"), json={"active": False}, headers=H).status_code == 404
    )
    assert client.delete(url(mine, f"/{row_id}"), headers=H).status_code == 404
    anon = TestClient(client.app)
    assert anon.get(url(mine)).status_code == 401
    with sessions() as db:
        assert db.get(Project, mine) is not None and db.scalars(select(User)).first() is not None
