from __future__ import annotations

import copy
import json
from typing import Any

import pytest

from cobble.orchestrator.plan_schema import (
    SCHEMA_PATH,
    PlanInvalid,
    parse_plan_reply,
    plan_json_schema,
    schema_text,
    validate_plan,
)

from .planning import load_script


def good() -> dict[str, Any]:
    return {
        "milestones": [{"id": "M1", "title": "First"}, {"id": "M2", "title": "Second"}],
        "tasks": [
            {
                "id": "T-001",
                "title": "Skeleton",
                "milestone": "M1",
                "depends_on": [],
                "files": ["app/main.py", "tests/test_main.py"],
                "acceptance": ["GET /api/health returns 200"],
                "tests": "tests/test_main.py",
                "size": "S",
                "role": "backend",
            },
            {
                "id": "T-002",
                "title": "Page",
                "milestone": "M2",
                "depends_on": ["T-001"],
                "files": ["web/index.html"],
                "acceptance": ["GET / returns the page"],
                "tests": "tests/test_web.py",
                "size": "M",
                "role": "frontend",
            },
        ],
    }


def errors_of(plan: dict[str, Any]) -> list[str]:
    with pytest.raises(PlanInvalid) as info:
        validate_plan(plan)
    return info.value.errors


def mutated(change: Any) -> dict[str, Any]:
    plan = copy.deepcopy(good())
    change(plan)
    return plan


def test_a_valid_plan_is_accepted() -> None:
    plan = validate_plan(good())
    assert [t.id for t in plan.tasks] == ["T-001", "T-002"]
    assert plan.tasks[1].depends_on == ["T-001"]


def test_depends_on_is_optional() -> None:
    plan = good()
    del plan["tasks"][0]["depends_on"]
    assert validate_plan(plan).tasks[0].depends_on == []


@pytest.mark.parametrize("acceptance", [[], [""], ["   "]])
def test_task_without_acceptance_is_rejected(acceptance: list[str]) -> None:
    errors = errors_of(mutated(lambda p: p["tasks"][0].update(acceptance=acceptance)))
    assert len(errors) == 1
    assert errors[0].startswith("tasks[0].acceptance")


def test_missing_acceptance_field_is_rejected() -> None:
    errors = errors_of(mutated(lambda p: p["tasks"][1].pop("acceptance")))
    assert errors == ["tasks[1].acceptance: is required"]


@pytest.mark.parametrize("size", ["L", "XL", "s", "", 3])
def test_size_other_than_s_or_m_is_rejected(size: object) -> None:
    errors = errors_of(mutated(lambda p: p["tasks"][1].update(size=size)))
    assert len(errors) == 1
    assert errors[0].startswith("tasks[1].size")


def test_size_l_message_tells_to_split() -> None:
    errors = errors_of(mutated(lambda p: p["tasks"][0].update(size="L")))
    assert "'S' or 'M'" in errors[0]
    assert "split" in errors[0]


@pytest.mark.parametrize(
    "files",
    [[], [""], ["/etc/passwd"], ["../secret.py"], ["app/../../x.py"], ["C:/x.py"], ["\\x.py"]],
)
def test_bad_files_are_rejected(files: list[str]) -> None:
    errors = errors_of(mutated(lambda p: p["tasks"][0].update(files=files)))
    assert len(errors) == 1
    assert errors[0].startswith("tasks[0].files")


def test_dotted_file_names_are_not_confused_with_parent_paths() -> None:
    plan = mutated(lambda p: p["tasks"][0].update(files=["app/..hidden.py", "a/b.c/d"]))
    validate_plan(plan)


@pytest.mark.parametrize("tests", ["", "   "])
def test_empty_tests_is_rejected(tests: str) -> None:
    errors = errors_of(mutated(lambda p: p["tasks"][0].update(tests=tests)))
    assert len(errors) == 1
    assert errors[0].startswith("tasks[0].tests")


@pytest.mark.parametrize("task_id", ["T1", "T-", "t-001", "X-001", "T-00a", ""])
def test_malformed_task_id_is_rejected(task_id: str) -> None:
    errors = errors_of(mutated(lambda p: p["tasks"][0].update(id=task_id)))
    assert any(e.startswith("tasks[0].id") for e in errors)


@pytest.mark.parametrize("milestone_id", ["m1", "M", "M-1", "1", ""])
def test_malformed_milestone_id_is_rejected(milestone_id: str) -> None:
    errors = errors_of(mutated(lambda p: p["milestones"][0].update(id=milestone_id)))
    assert any(e.startswith("milestones[0].id") for e in errors)


def test_duplicate_task_ids_are_rejected() -> None:
    errors = errors_of(mutated(lambda p: p["tasks"][1].update(id="T-001", depends_on=[])))
    assert errors == ["tasks: duplicate id T-001"]


def test_duplicate_milestone_ids_are_rejected() -> None:
    errors = errors_of(mutated(lambda p: p["milestones"][1].update(id="M1")))
    assert errors == [
        "milestones: duplicate id M1",
        "tasks[1] (T-002).milestone: unknown milestone M2",
    ]


def test_unknown_milestone_is_rejected() -> None:
    errors = errors_of(mutated(lambda p: p["tasks"][0].update(milestone="M9")))
    assert errors == ["tasks[0] (T-001).milestone: unknown milestone M9"]


def test_unknown_dependency_is_rejected() -> None:
    errors = errors_of(mutated(lambda p: p["tasks"][1].update(depends_on=["T-099"])))
    assert errors == ["tasks[1] (T-002).depends_on: unknown task T-099"]


def test_self_dependency_is_a_cycle() -> None:
    errors = errors_of(mutated(lambda p: p["tasks"][0].update(depends_on=["T-001"])))
    assert errors == ["dependency cycle: T-001 -> T-001"]


def test_dependency_cycle_is_rejected() -> None:
    errors = errors_of(mutated(lambda p: p["tasks"][0].update(depends_on=["T-002"])))
    assert len(errors) == 1
    assert errors[0].startswith("dependency cycle: ")
    assert "T-001" in errors[0]
    assert "T-002" in errors[0]


def test_longer_cycle_is_found() -> None:
    def change(plan: dict[str, Any]) -> None:
        third = copy.deepcopy(plan["tasks"][1])
        third.update(id="T-003", depends_on=["T-002"])
        plan["tasks"].append(third)
        plan["tasks"][0]["depends_on"] = ["T-003"]

    errors = errors_of(mutated(change))
    assert errors == ["dependency cycle: T-001 -> T-003 -> T-002 -> T-001"]


def test_no_milestones_is_rejected() -> None:
    errors = errors_of(mutated(lambda p: p.update(milestones=[])))
    assert errors == ["milestones: at least one milestone is required"]


def test_no_tasks_is_rejected() -> None:
    errors = errors_of(mutated(lambda p: p.update(tasks=[])))
    assert errors == ["tasks: at least one task is required"]


@pytest.mark.parametrize("role", ["manager", "Backend", "", None])
def test_bad_role_is_rejected(role: object) -> None:
    errors = errors_of(mutated(lambda p: p["tasks"][0].update(role=role)))
    assert len(errors) == 1
    assert errors[0].startswith("tasks[0].role")


@pytest.mark.parametrize("role", ["backend", "frontend", "fullstack", "devops", "docs"])
def test_every_documented_role_is_accepted(role: str) -> None:
    validate_plan(mutated(lambda p: p["tasks"][0].update(role=role)))


def test_unknown_fields_are_rejected() -> None:
    errors = errors_of(mutated(lambda p: p["tasks"][0].update(priority=1)))
    assert errors == ["tasks[0].priority: is not an allowed field"]


def test_wrong_types_are_rejected_not_coerced() -> None:
    errors = errors_of(mutated(lambda p: p["tasks"][0].update(acceptance="one sentence")))
    assert len(errors) == 1
    assert errors[0].startswith("tasks[0].acceptance")


def test_not_an_object_is_rejected() -> None:
    errors = errors_of([])  # type: ignore[arg-type]
    assert len(errors) == 1
    assert errors[0].startswith("plan: has the wrong type")


def test_all_violations_are_reported_together() -> None:
    def change(plan: dict[str, Any]) -> None:
        plan["tasks"][0]["acceptance"] = []
        plan["tasks"][1]["size"] = "L"

    assert len(errors_of(mutated(change))) == 2


# --- reply parsing -------------------------------------------------------------------------


def test_parse_reply_reads_a_fenced_block() -> None:
    text = "Here is the plan:\n```json\n" + json.dumps(good()) + "\n```\nDone."
    assert len(parse_plan_reply(text).tasks) == 2


def test_parse_reply_reads_bare_json() -> None:
    assert len(parse_plan_reply(json.dumps(good())).tasks) == 2


def test_parse_reply_reads_json_surrounded_by_chatter() -> None:
    assert len(parse_plan_reply("Sure! " + json.dumps(good()) + " Enjoy.").tasks) == 2


def test_parse_reply_rejects_text_that_is_not_json() -> None:
    with pytest.raises(PlanInvalid) as info:
        parse_plan_reply("I cannot do that")
    assert info.value.errors[0].startswith("the reply is not valid JSON")


def test_parse_reply_rejects_truncated_json() -> None:
    with pytest.raises(PlanInvalid):
        parse_plan_reply(json.dumps(good())[:60])


# --- JSON Schema and the reference plan ---------------------------------------------------


def test_exported_json_schema_is_in_sync() -> None:
    on_disk = SCHEMA_PATH.read_text("utf-8")
    assert on_disk == schema_text(), (
        "plan.schema.json is out of date: run `python -m cobble.orchestrator.plan_schema`"
    )
    assert json.loads(on_disk) == json.loads(json.dumps(plan_json_schema()))


def test_json_schema_encodes_the_main_rules() -> None:
    schema = json.loads(SCHEMA_PATH.read_text("utf-8"))
    task = schema["$defs"]["Task"]["properties"]
    assert task["size"]["enum"] == ["S", "M"]
    assert task["acceptance"]["minItems"] == 1
    assert task["files"]["minItems"] == 1
    assert schema["properties"]["tasks"]["minItems"] == 1
    assert schema["properties"]["milestones"]["minItems"] == 1
    assert schema["$defs"]["Task"]["additionalProperties"] is False


@pytest.mark.parametrize("lang", ["en", "fr"])
def test_the_reference_todo_plan_is_valid(lang: str) -> None:
    plan = validate_plan(load_script().valid_plan(lang))
    assert len(plan.milestones) <= 3
    assert 8 <= len(plan.tasks) <= 12
    assert {t.size for t in plan.tasks} <= {"S", "M"}
    assert all(t.acceptance and t.tests and t.files for t in plan.tasks)
    assert any(t.depends_on for t in plan.tasks)
