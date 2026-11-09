"""The "ask the human" protocol (ADR 0025): detection, bounds, and the `question` run state."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from cobble_agent_service.config import Settings
from cobble_agent_service.detector import LoopDetector
from cobble_agent_service.questions import MAX_CHOICES, MAX_QUESTION_CHARS, parse_question
from cobble_agent_service.runs import RunManager

from .conftest import Ctx, FakeEngine, finished, make_request, new_manager


async def run_to_end(settings: Settings, engine: FakeEngine) -> tuple[str, RunManager]:
    manager = new_manager(settings, engine)
    await manager.start()
    run_id = await manager.create(make_request(settings))
    await finished(manager, run_id)
    return run_id, manager


def test_question_line_is_recorded_once_and_bounded() -> None:
    d = LoopDetector()
    d.feed(b'[cobble:question] {"question": "First?", "choices": ["a", "b"]}\n')
    d.feed(b'[cobble:question] {"question": "Second?"}\n')
    assert d.question == {"question": "First?", "choices": ["a", "b"]}
    line = "[cobble:question] " + json.dumps(
        {"question": "x" * 5000, "choices": list("abcdefghij")}
    )
    big = parse_question(line)
    assert big is not None
    assert len(big["question"]) == MAX_QUESTION_CHARS and len(big["choices"]) == MAX_CHOICES


def test_invalid_question_lines_are_ignored() -> None:
    for line in (
        "[cobble:question]",
        "[cobble:question] []",
        '[cobble:question] {"question": 3}',
        '[cobble:question] {"question": "  "}',
        '{"question": "no prefix"}',
    ):
        assert parse_question(line) is None


async def test_question_line_ends_the_run_as_question(settings: Settings, remote: Path) -> None:
    async def script(ctx: Ctx) -> int:
        ctx.emit("thinking\n")
        ctx.commit()
        ctx.emit('[cobble:question] {"question": "Include taxes?", "choices": ["yes", "no"]}\n')
        await asyncio.sleep(60)  # would burn tokens: the service must stop it
        return 0

    engine = FakeEngine(script)
    run_id, manager = await run_to_end(settings, engine)
    status = manager.status(run_id)
    assert status.state == "question" and status.reason == "question"
    assert status.question == {"question": "Include taxes?", "choices": ["yes", "no"]}
    assert engine.killed  # the container was stopped
    assert status.pushed and status.commits == 1  # the work so far is kept on the branch
    await manager.shutdown()


async def test_question_printed_when_the_agent_exits_is_a_question(settings: Settings) -> None:
    async def script(ctx: Ctx) -> int:
        ctx.emit('[cobble:question] {"question": "Which database?"}\n')
        return 0

    run_id, manager = await run_to_end(settings, FakeEngine(script))
    status = manager.status(run_id)
    assert status.state == "question"
    assert status.question == {"question": "Which database?", "choices": []}
    await manager.shutdown()


async def test_malformed_question_is_ignored(settings: Settings) -> None:
    async def script(ctx: Ctx) -> int:
        ctx.emit("[cobble:question] not json\n")
        return 1

    run_id, manager = await run_to_end(settings, FakeEngine(script))
    status = manager.status(run_id)
    assert status.state == "failed" and status.question is None
    await manager.shutdown()
