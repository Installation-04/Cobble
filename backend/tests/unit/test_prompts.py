from __future__ import annotations

import copy
import json

from cobble.orchestrator import prompts

from .planning import CASSETTES, load_script

HISTORY = [
    {"role": "user", "content": "I want a to-do app"},
    {"role": "assistant", "content": "For whom?"},
    {"role": "user", "content": "Me"},
]


def test_interview_messages_are_deterministic() -> None:
    assert prompts.interview_messages(HISTORY, "en") == prompts.interview_messages(
        copy.deepcopy(HISTORY), "en"
    )


def test_interview_is_system_prompt_then_the_history() -> None:
    messages = prompts.interview_messages(HISTORY, "en")
    assert messages[0]["role"] == "system"
    assert messages[1:] == HISTORY


def test_extra_keys_of_stored_messages_do_not_change_the_prompt() -> None:
    rich = [{**m, "id": "abc"} for m in HISTORY]
    assert prompts.interview_messages(rich, "en") == prompts.interview_messages(HISTORY, "en")


def test_language_instruction_follows_the_user_language() -> None:
    en = prompts.interview_messages(HISTORY, "en")[0]["content"]
    fr = prompts.interview_messages(HISTORY, "fr")[0]["content"]
    assert "Reply in English" in en
    assert "Reply in French" in fr
    assert en != fr
    assert "Reply in English" in prompts.interview_messages(HISTORY, "de")[0]["content"]


def test_interview_prompt_asks_questions_proposes_a_stack_and_stays_short() -> None:
    system = prompts.interview_messages(HISTORY, "en")[0]["content"]
    assert "targeted questions instead of guessing" in system
    assert "FastAPI" in system
    assert "short" in system


def test_spec_prompt_lists_the_sections_and_the_language() -> None:
    messages = prompts.spec_messages(HISTORY, "fr")
    system = messages[0]["content"]
    for section in ("Features", "Screens", "Data model", "Constraints", "Out of scope"):
        assert section in system
    assert "Markdown" in system
    assert "French" in system
    assert "[user] I want a to-do app" in messages[1]["content"]
    assert messages == prompts.spec_messages(HISTORY, "fr")


def test_spec_feedback_adds_the_previous_spec_and_the_request() -> None:
    plain = prompts.spec_messages(HISTORY, "en")
    revised = prompts.spec_messages(HISTORY, "en", feedback="Add dark mode", previous_spec="# Old")
    assert revised != plain
    assert "# Old" in revised[1]["content"]
    assert "Add dark mode" in revised[1]["content"]
    # Feedback without a previous spec has nothing to revise.
    assert prompts.spec_messages(HISTORY, "en", feedback="x") == plain


def test_plan_prompt_demands_only_json_with_small_testable_tasks() -> None:
    messages = prompts.plan_messages("# Spec", "en")
    system = messages[0]["content"]
    assert "ONLY one JSON object" in system
    assert 'never "L"' in system
    assert "BEFORE the implementation" in system
    assert "testable" in system
    assert "English" in system
    assert "# Spec" in messages[1]["content"]
    assert messages == prompts.plan_messages("# Spec", "en")


def test_plan_prompt_example_is_valid_json_shape() -> None:
    system = prompts.plan_messages("# Spec", "en")[0]["content"]
    line = next(line for line in system.splitlines() if line.startswith('{"milestones"'))
    example = json.loads(line)
    assert set(example["tasks"][0]) == {
        "id",
        "title",
        "milestone",
        "depends_on",
        "files",
        "acceptance",
        "tests",
        "size",
        "role",
    }


def test_retry_messages_feed_the_errors_back() -> None:
    base = prompts.plan_messages("# Spec", "en")
    retry = prompts.retry_messages(base, "bad reply", ["tasks[0].size: nope", "other"])
    assert retry[: len(base)] == base
    assert retry[-2] == {"role": "assistant", "content": "bad reply"}
    assert retry[-1]["role"] == "user"
    assert "- tasks[0].size: nope\n- other" in retry[-1]["content"]


def test_scripted_cassettes_match_the_current_prompts() -> None:
    """Fails after a prompt change: regenerate with providers/fake-llm/scripts."""
    script = load_script()
    for stem, cassette in script.build_cassettes().items():
        path = CASSETTES / f"{stem}.json"
        assert path.exists(), f"missing cassette {path.name}"
        assert path.read_text("utf-8") == script.render(cassette), (
            f"{path.name} is out of date: cd providers/fake-llm && "
            "uv run python scripts/make_todo_cassettes.py"
        )
    wanted = {f"{stem}.json" for stem in script.build_cassettes()}
    assert {p.name for p in CASSETTES.glob("todo-*.json")} == wanted
