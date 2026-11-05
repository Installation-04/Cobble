"""Mockup variants (ADR 0018): parsing, the planner job, the API and the plan context."""

from __future__ import annotations

import json
import uuid
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from cobble.db import MockupVariant, Project, Spec
from cobble.events import JOBS_STREAM
from cobble.orchestrator.mockups import MockupsInvalid, mockup_messages, parse_mockups

from .fakes import FakeStreamRedis
from .planning import ScriptedLLM, events_of, load_script, make_project
from .test_planner_service import add_spec, phase_of, service
from .test_planning_api import API, H, client_for, code, owner_of

SCRIPT = load_script()
VALID_PLAN = json.dumps(SCRIPT.valid_plan("en"))


def variants_reply(n: int = 3, **override: Any) -> str:
    items = [
        {
            "title": f"Layout {i}",
            "summary": f"Idea {i}.",
            "wireframe": f"+------+\n| V{i}   |\n+------+",
        }
        for i in range(1, n + 1)
    ]
    items[0].update(override)
    return json.dumps({"variants": items})


def enable(sessions: sessionmaker[Session], pid: uuid.UUID, phase: str = "spec_review") -> None:
    with sessions() as db:
        project = db.get(Project, pid)
        assert project is not None
        project.mockups_enabled = True
        project.phase = phase
        db.commit()


def stored(sessions: sessionmaker[Session], pid: uuid.UUID) -> list[MockupVariant]:
    with sessions() as db:
        return list(
            db.scalars(
                select(MockupVariant)
                .where(MockupVariant.project_id == pid)
                .order_by(MockupVariant.position)
            )
        )


# --- parsing and sanitising ------------------------------------------------------------------


def test_parse_keeps_text_and_drops_control_characters() -> None:
    reply = variants_reply(2, title="  Big\x00 list  ", wireframe="+--+\x1b[31m\n|\tx|\n\n\n")
    first, _second = parse_mockups(reply, 3)
    assert first.title == "Big list"
    assert first.wireframe == "+--+[31m\n|    x|"


def test_parse_never_turns_markup_into_anything_else() -> None:
    script = "<script>alert(1)</script>"
    first, *_ = parse_mockups(variants_reply(2, wireframe=script, summary=script), 3)
    assert first.wireframe == script and first.summary == script  # stored verbatim as text


def test_parse_caps_sizes_and_variant_count() -> None:
    wireframe = "\n".join(["x" * 500] * 100)
    variants = parse_mockups(variants_reply(3, wireframe=wireframe, title="t" * 500), 2)
    assert len(variants) == 2
    assert len(variants[0].title) == 120
    lines = variants[0].wireframe.split("\n")
    assert len(lines) == 30 and all(len(line) <= 80 for line in lines)


@pytest.mark.parametrize(
    "reply",
    [
        "not json",
        json.dumps({"variants": "x"}),
        json.dumps({"variants": [{"title": "a", "summary": "b", "wireframe": "c"}]}),  # only one
        variants_reply(2, wireframe="   "),
        variants_reply(2, title=3),
    ],
)
def test_parse_rejects_bad_replies(reply: str) -> None:
    with pytest.raises(MockupsInvalid):
        parse_mockups(reply, 3)


def test_the_prompt_asks_for_plain_text_in_the_user_language() -> None:
    system = mockup_messages("# Spec", "fr", 2)[0]["content"]
    assert "French" in system and "Exactly 2 variants" in system and "never HTML" in system


# --- job -------------------------------------------------------------------------------------


def test_the_job_stores_variants_through_the_planner_role(
    sessions: sessionmaker[Session],
) -> None:
    pid = make_project(sessions)
    add_spec(sessions, pid)
    enable(sessions, pid)
    redis = FakeStreamRedis()
    llm = ScriptedLLM(variants_reply(3))
    assert service(sessions, llm, redis).run_job("mockups", pid, count=3) is True
    rows = stored(sessions, pid)
    assert [r.title for r in rows] == ["Layout 1", "Layout 2", "Layout 3"]
    assert not any(r.chosen for r in rows)
    assert phase_of(sessions, pid) == "spec_review"
    assert [n for n, _ in events_of(redis, pid)] == ["job.started", "mockups.updated"]


def test_a_new_batch_replaces_the_old_one_and_the_choice(sessions: sessionmaker[Session]) -> None:
    pid = make_project(sessions)
    add_spec(sessions, pid)
    enable(sessions, pid)
    svc = service(sessions, ScriptedLLM(variants_reply(3), variants_reply(2)))
    svc.run_job("mockups", pid)
    choose_first(sessions, pid)
    svc.run_job("mockups", pid, count=2)
    rows = stored(sessions, pid)
    assert len(rows) == 2 and not any(r.chosen for r in rows)


def test_an_invalid_reply_is_retried_once_then_fails(sessions: sessionmaker[Session]) -> None:
    pid = make_project(sessions)
    add_spec(sessions, pid)
    enable(sessions, pid)
    llm = ScriptedLLM("nope", variants_reply(2))
    assert service(sessions, llm, FakeStreamRedis()).run_job("mockups", pid) is True
    assert len(llm.calls) == 2 and len(stored(sessions, pid)) == 2

    pid2 = make_project(sessions)
    add_spec(sessions, pid2)
    enable(sessions, pid2)
    redis2 = FakeStreamRedis()
    assert service(sessions, ScriptedLLM("no", "no"), redis2).run_job("mockups", pid2) is False
    failed = events_of(redis2, pid2)[-1]
    assert failed == ("job.failed", {"kind": "mockups", "code": "mockups_invalid"})


def test_the_job_does_nothing_without_an_approved_spec(sessions: sessionmaker[Session]) -> None:
    pid = make_project(sessions)
    add_spec(sessions, pid, status="draft")
    enable(sessions, pid)
    llm = ScriptedLLM()
    assert service(sessions, llm).run_job("mockups", pid) is True
    assert llm.calls == [] and stored(sessions, pid) == []


# --- the chosen variant feeds the plan -------------------------------------------------------


def choose_first(sessions: sessionmaker[Session], pid: uuid.UUID) -> None:
    with sessions() as db:
        row = db.scalars(
            select(MockupVariant)
            .where(MockupVariant.project_id == pid)
            .order_by(MockupVariant.position)
        ).first()
        assert row is not None
        row.chosen = True
        db.commit()


def test_the_chosen_variant_is_part_of_the_plan_prompt(sessions: sessionmaker[Session]) -> None:
    pid = make_project(sessions)
    add_spec(sessions, pid)
    enable(sessions, pid)
    service(sessions, ScriptedLLM(variants_reply(2))).run_job("mockups", pid)
    choose_first(sessions, pid)
    llm = ScriptedLLM(VALID_PLAN)
    assert service(sessions, llm).run_job("plan", pid) is True
    prompt = llm.calls[0][1]["content"]
    assert "chose this mockup" in prompt and "| V1" in prompt


def test_the_plan_prompt_is_unchanged_when_the_option_is_off(
    sessions: sessionmaker[Session],
) -> None:
    pid = make_project(sessions)
    add_spec(sessions, pid)
    with sessions() as db:
        project = db.get(Project, pid)
        assert project is not None
        project.phase = "spec_review"
        db.add(
            MockupVariant(
                project_id=pid, position=1, title="t", summary="s", wireframe="w", chosen=True
            )
        )
        db.commit()
    llm = ScriptedLLM(VALID_PLAN)
    service(sessions, llm).run_job("plan", pid)
    assert "mockup" not in llm.calls[0][1]["content"]


# --- API -------------------------------------------------------------------------------------


@pytest.fixture
def redis() -> FakeStreamRedis:
    return FakeStreamRedis()


@pytest.fixture
def ready(sessions: sessionmaker[Session]) -> uuid.UUID:
    pid = make_project(sessions)
    add_spec(sessions, pid)
    with sessions() as db:
        project = db.get(Project, pid)
        assert project is not None
        project.phase = "spec_review"
        db.commit()
    return pid


def jobs(redis: FakeStreamRedis) -> list[dict[str, Any]]:
    return [json.loads(e["job"]) for e in redis.entries(JOBS_STREAM)]


def test_the_switch_is_off_by_default_and_toggled_by_patch(
    sessions: sessionmaker[Session], redis: FakeStreamRedis, ready: uuid.UUID
) -> None:
    api = client_for(sessions, redis, owner_of(sessions, ready))
    assert api.get(f"{API}/projects").json()[0]["mockups_enabled"] is False
    reply = api.patch(f"{API}/projects/{ready}", json={"mockups_enabled": True}, headers=H)
    assert reply.json()["mockups_enabled"] is True


def test_generate_needs_the_switch_and_an_approved_spec(
    sessions: sessionmaker[Session], redis: FakeStreamRedis, ready: uuid.UUID
) -> None:
    api = client_for(sessions, redis, owner_of(sessions, ready))
    url = f"{API}/projects/{ready}/mockups/generate"
    assert code(api.post(url, json={}, headers=H)) == "mockups_disabled"
    enable(sessions, ready)
    assert api.post(url, json={"count": 4}, headers=H).status_code == 422
    assert api.post(url, json={"count": 2, "feedback": " calmer "}, headers=H).status_code == 202
    assert jobs(redis)[-1]["kind"] == "mockups"
    assert jobs(redis)[-1]["count"] == 2 and jobs(redis)[-1]["feedback"] == "calmer"
    with sessions() as db:
        spec = db.scalars(select(Spec)).first()
        assert spec is not None
        spec.status = "draft"
        db.commit()
    assert code(api.post(url, json={}, headers=H)) == "wrong_phase"


def test_choose_marks_exactly_one_and_plan_generation_waits_for_it(
    sessions: sessionmaker[Session], redis: FakeStreamRedis, ready: uuid.UUID
) -> None:
    enable(sessions, ready)
    service(sessions, ScriptedLLM(variants_reply(3))).run_job("mockups", ready)
    api = client_for(sessions, redis, owner_of(sessions, ready))
    listed = api.get(f"{API}/projects/{ready}/mockups").json()
    assert [v["position"] for v in listed] == [1, 2, 3]

    blocked = api.post(f"{API}/projects/{ready}/plan/generate", json={}, headers=H)
    assert code(blocked) == "mockup_choice_required"
    reply = api.post(f"{API}/projects/{ready}/mockups/{listed[1]['id']}/choose", headers=H)
    assert [v["chosen"] for v in reply.json()] == [False, True, False]
    reply = api.post(f"{API}/projects/{ready}/mockups/{listed[2]['id']}/choose", headers=H)
    assert [v["chosen"] for v in reply.json()] == [False, False, True]
    assert api.post(f"{API}/projects/{ready}/plan/generate", json={}, headers=H).status_code == 202
    missing = api.post(f"{API}/projects/{ready}/mockups/{uuid.uuid4()}/choose", headers=H)
    assert code(missing) == "not_found"


def test_without_the_switch_plan_generation_is_not_gated(
    sessions: sessionmaker[Session], redis: FakeStreamRedis, ready: uuid.UUID
) -> None:
    api = client_for(sessions, redis, owner_of(sessions, ready))
    assert api.post(f"{API}/projects/{ready}/plan/generate", json={}, headers=H).status_code == 202


def test_another_user_cannot_see_or_choose(
    sessions: sessionmaker[Session], redis: FakeStreamRedis, ready: uuid.UUID
) -> None:
    other = make_project(sessions)
    api = client_for(sessions, redis, owner_of(sessions, other))
    assert api.get(f"{API}/projects/{ready}/mockups").status_code == 404
    url = f"{API}/projects/{ready}/mockups/{uuid.uuid4()}/choose"
    assert api.post(url, headers=H).status_code == 404
