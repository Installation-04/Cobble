"""Agents asking the user (ADR 0025): scheduler flow, bounds, controls and the API."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from cobble.capabilities.agent import AgentOutcome, AgentQuestion
from cobble.capabilities.fakes import FakeAgentRunner
from cobble.db import Task, TaskQuestion, TaskRun
from cobble.providers.agent_service import HttpAgentRunner
from cobble.scheduler import control, questions, rules

from .fakes import FakeStreamRedis
from .scheduling import Harness, make_ready_project
from .test_tasks_api import API, H, client_for

Q = AgentOutcome.QUESTION
DONE = AgentOutcome.DONE
KEY = ("T-001", "test-writer", 1)


@pytest.fixture
def pid(sessions: sessionmaker[Session]) -> uuid.UUID:
    return make_ready_project(sessions)


def asking(sessions: sessionmaker[Session]) -> Harness:
    h = Harness(sessions, agents=FakeAgentRunner(script={KEY: Q}))
    return h


def question_rows(h: Harness) -> list[TaskQuestion]:
    with h.sessions() as db:
        return list(db.scalars(select(TaskQuestion).order_by(TaskQuestion.created_at)))


def settle(h: Harness, pid: uuid.UUID, ticks: int = 4) -> None:
    for _ in range(ticks):
        h.scheduler.tick()


def test_a_question_parks_the_task_without_using_an_attempt(
    sessions: sessionmaker[Session], pid: uuid.UUID
) -> None:
    h = asking(sessions)
    h.start(pid)
    settle(h, pid)
    t1 = h.tasks(pid)["T-001"]
    assert t1.state == rules.WAITING_HUMAN
    assert t1.attempts == 0 and t1.last_error is None  # not a failure
    runs = h.runs("T-001", pid)
    assert [(r.kind, r.state) for r in runs] == [("test-writer", "question")]
    (row,) = question_rows(h)
    assert row.status == "open" and row.question == "Should the amount include taxes?"
    assert row.choices == ["yes", "no"] and row.run_id == runs[0].id
    events = h.events(pid)
    asked = [p for t, p in events if t == "task.question"]
    assert asked == [
        {
            "task_id": "T-001",
            "question_id": str(row.id),
            "question": row.question,
            "choices": ["yes", "no"],
        }
    ]
    started = len(h.agents.runs)
    settle(h, pid, 5)  # waiting costs nothing: no new run
    assert len(h.agents.runs) == started
    assert h.tasks(pid)["T-001"].state == rules.WAITING_HUMAN


def test_waiting_task_does_not_end_or_block_the_project(
    sessions: sessionmaker[Session], pid: uuid.UUID
) -> None:
    h = asking(sessions)
    h.start(pid)
    settle(h, pid, 10)
    states = h.states(pid)
    assert states["T-001"] == rules.WAITING_HUMAN
    assert h.phase(pid) == "building"
    assert rules.WAITING_HUMAN not in rules.RUNNING  # it holds no agent slot
    assert rules.BLOCKED not in states.values()  # dependents just wait, they are not dead


def test_answer_resumes_the_same_step_with_the_answer_in_the_prompt(
    sessions: sessionmaker[Session], pid: uuid.UUID
) -> None:
    h = asking(sessions)
    h.start(pid)
    settle(h, pid)
    (row,) = question_rows(h)
    h.agents.script.clear()  # the next run does not ask again
    with sessions() as db:
        done = questions.answer(db, pid, row.id, "yes, taxes included", redis=h.redis)  # type: ignore[arg-type]
        assert done.status == "answered"
    assert h.tasks(pid)["T-001"].state == rules.PAUSED
    types = [t for t, _ in h.events(pid)]
    assert "task.answered" in types
    settle(h, pid, 3)
    resumed = [r for r in h.agents.runs if r.task_id == h.tasks(pid)["T-001"].id]
    assert [r.role.value for r in resumed][:2] == ["test-writer", "test-writer"]
    prompt = resumed[1].instructions
    assert "A: yes, taxes included" in prompt
    assert "Q: Should the amount include taxes?" in prompt
    assert "at most 2 more question" in prompt  # one of three used
    assert h.tasks(pid)["T-001"].state != rules.WAITING_HUMAN
    h.run_until(pid)  # and the project completes


def test_skip_tells_the_agent_to_decide(sessions: sessionmaker[Session], pid: uuid.UUID) -> None:
    h = asking(sessions)
    h.start(pid)
    settle(h, pid)
    (row,) = question_rows(h)
    h.agents.script.clear()
    with sessions() as db:
        assert questions.answer(db, pid, row.id, None).status == "skipped"
    settle(h, pid, 3)
    prompt = h.agents.runs[1].instructions
    assert "no answer: decide yourself" in prompt


def test_at_most_three_questions_per_task(sessions: sessionmaker[Session], pid: uuid.UUID) -> None:
    h = asking(sessions)
    h.start(pid)
    for index in range(3):
        settle(h, pid)
        rows = question_rows(h)
        assert len(rows) == index + 1 and rows[-1].status == "open"
        with sessions() as db:
            questions.answer(db, pid, rows[-1].id, f"answer {index}")
    settle(h, pid, 3)
    # The fourth ask (the scripted agent ignores its budget) is a failed run, not a fourth
    # question: no endless loop of free restarts.
    rows = question_rows(h)
    assert len(rows) == 3 and all(r.status == "answered" for r in rows)
    states = [r.state for r in h.runs("T-001", pid)]
    assert states.count("question") == 3 and "failed" in states
    assert h.tasks(pid)["T-001"].state != rules.WAITING_HUMAN
    assert questions.OVER_LIMIT_LOG in (h.tasks(pid)["T-001"].last_error or "")
    assert "Do not ask the user anything more" in h.agents.runs[3].instructions


def test_answer_errors(sessions: sessionmaker[Session], pid: uuid.UUID) -> None:
    h = asking(sessions)
    h.start(pid)
    settle(h, pid)
    (row,) = question_rows(h)
    with sessions() as db:
        with pytest.raises(questions.QuestionError) as empty:
            questions.answer(db, pid, row.id, "   ")
        assert (empty.value.status, empty.value.code) == (422, "answer_empty")
        with pytest.raises(questions.QuestionError) as other:
            questions.answer(db, uuid.uuid4(), row.id, "x")  # another project
        assert other.value.status == 404
        questions.answer(db, pid, row.id, "ok")
        with pytest.raises(questions.QuestionError) as again:
            questions.answer(db, pid, row.id, "twice")
        assert (again.value.status, again.value.code) == (409, "question_closed")


def test_text_is_bounded_and_cleaned(sessions: sessionmaker[Session], pid: uuid.UUID) -> None:
    h = Harness(sessions, agents=FakeAgentRunner(script={KEY: Q}))
    h.agents.question = AgentQuestion("x\x00" * 3000, (*(f"c{i}\x07" for i in range(10)), ""))
    h.start(pid)
    settle(h, pid)
    (row,) = question_rows(h)
    assert len(row.question) == questions.QUESTION_CHARS and "\x00" not in row.question
    assert row.choices == [f"c{i}" for i in range(questions.MAX_CHOICES)]


def test_stop_closes_the_question_and_retry_starts_over(
    sessions: sessionmaker[Session], pid: uuid.UUID
) -> None:
    h = asking(sessions)
    h.start(pid)
    settle(h, pid)
    with sessions() as db:
        task = db.scalars(select(Task).where(Task.ref == "T-001")).one()
        control.apply(db, task, control.Action.PAUSE)  # no-op while waiting
        assert task.state == rules.WAITING_HUMAN
        control.apply(db, task, control.Action.STOP)
        assert task.state == rules.STOPPED
        assert db.scalars(select(TaskQuestion)).one().status == "skipped"
        control.apply(db, task, control.Action.RETRY)
        assert task.state == rules.TODO
        run = db.scalars(select(TaskRun).where(TaskRun.task_id == task.id)).one()
        assert run.state == "retired"


def test_a_waiting_task_cannot_be_started_by_a_stray_tick(
    sessions: sessionmaker[Session], pid: uuid.UUID
) -> None:
    h = asking(sessions)
    h.start(pid)
    settle(h, pid)
    with sessions() as db:
        task = db.scalars(select(Task).where(Task.ref == "T-001")).one()
        task.state = rules.PAUSED  # e.g. a manual database edit: the open question still guards
        db.commit()
    before = len(h.agents.runs)
    settle(h, pid, 3)
    assert not [r for r in h.agents.runs[before:] if r.task_id == h.tasks(pid)["T-001"].id]


# --- provider --------------------------------------------------------------------------------


def test_http_provider_maps_the_question_state() -> None:
    import httpx

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "run_id": "r1",
                "state": "question",
                "iterations": 1,
                "log_tail": "tail",
                "question": {"question": " Which DB? ", "choices": ["pg", 3, " sqlite "]},
            },
        )

    runner = HttpAgentRunner("http://agent", "t", transport=httpx.MockTransport(handler))
    result = runner.poll("r1")
    assert result is not None and result.outcome is Q
    assert result.question == AgentQuestion("Which DB?", ("pg", "sqlite"))


def test_http_provider_without_a_readable_question_is_a_failure() -> None:
    import httpx

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"state": "question", "question": None})

    runner = HttpAgentRunner("http://agent", "t", transport=httpx.MockTransport(handler))
    result = runner.poll("r1")
    assert result is not None and result.outcome is AgentOutcome.FAILED


# --- API -------------------------------------------------------------------------------------


def api_for(
    h: Harness, sessions: sessionmaker[Session], redis: FakeStreamRedis, pid: uuid.UUID
) -> TestClient:
    return client_for(sessions, redis, pid)


def test_api_lists_answers_and_skips(sessions: sessionmaker[Session], pid: uuid.UUID) -> None:
    redis = FakeStreamRedis()
    h = Harness(sessions, agents=FakeAgentRunner(script={KEY: Q}), redis=redis)
    h.start(pid)
    settle(h, pid)
    api = client_for(sessions, redis, pid)
    listing = api.get(f"{API}/projects/{pid}/questions").json()
    assert listing["open"] == 1
    item = listing["items"][0]
    assert item["task_id"] == "T-001" and item["choices"] == ["yes", "no"]
    url = f"{API}/projects/{pid}/questions/{item['id']}"
    assert api.post(f"{url}/answer", json={"answer": "yes"}).status_code == 403  # CSRF
    assert api.post(f"{url}/answer", headers=H, json={"answer": ""}).status_code == 422
    assert api.post(f"{url}/answer", headers=H, json={"answer": "x" * 2001}).status_code == 422
    ok = api.post(f"{url}/answer", headers=H, json={"answer": "yes"})
    assert ok.status_code == 200 and ok.json()["status"] == "answered"
    assert ok.json()["answer"] == "yes"
    assert api.post(f"{url}/skip", headers=H).status_code == 409
    assert api.post(f"{API}/projects/{pid}/questions/nope/skip", headers=H).status_code == 404
    assert api.get(f"{API}/projects/{pid}/questions").json()["open"] == 0
    assert h.tasks(pid)["T-001"].state == rules.PAUSED


def test_api_is_scoped_to_the_owner(sessions: sessionmaker[Session], pid: uuid.UUID) -> None:
    redis = FakeStreamRedis()
    h = Harness(sessions, agents=FakeAgentRunner(script={KEY: Q}), redis=redis)
    h.start(pid)
    settle(h, pid)
    other = make_ready_project(sessions)
    stranger = client_for(sessions, redis, other)
    (row,) = question_rows(h)
    assert stranger.get(f"{API}/projects/{pid}/questions").status_code == 404
    url = f"{API}/projects/{pid}/questions/{row.id}/skip"
    assert stranger.post(url, headers=H).status_code == 404
    # Own project, someone else's question id: 404 too.
    own = f"{API}/projects/{other}/questions/{row.id}/skip"
    assert stranger.post(own, headers=H).status_code == 404
