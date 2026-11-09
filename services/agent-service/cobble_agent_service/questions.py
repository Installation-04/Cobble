"""The "ask the human" protocol (ADR 0025).

An agent that cannot go on without a decision of the user ends its run with ONE line on its
output, whatever agent software produces it:

    [cobble:question] {"question": "Should the amount include taxes?", "choices": ["yes", "no"]}

`choices` is optional. The runner image turns a file `.cobble/question.json` (same JSON) into
that line when the agent exits, so an agent that can only write files can ask too. The first
valid line of a run wins; later ones are ignored. Text is bounded here (and again by the
backend): a runaway agent cannot fill the database with a question.
"""

from __future__ import annotations

import json
import re
from typing import Any

PREFIX = "[cobble:question]"
MAX_QUESTION_CHARS = 2000
MAX_CHOICES = 6
MAX_CHOICE_CHARS = 200

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _clean(text: str, limit: int) -> str:
    return _CONTROL.sub("", text).strip()[:limit]


def parse_question(line: str) -> dict[str, Any] | None:
    """`{"question": str, "choices": [str, ...]}` from a marker line, or None if invalid."""
    line = line.strip()
    if not line.startswith(PREFIX):
        return None
    try:
        data = json.loads(line[len(PREFIX) :])
    except ValueError:
        return None
    if not isinstance(data, dict) or not isinstance(data.get("question"), str):
        return None
    question = _clean(data["question"], MAX_QUESTION_CHARS)
    if not question:
        return None
    raw = data.get("choices")
    choices: list[str] = []
    if isinstance(raw, list):
        for item in raw[:MAX_CHOICES]:
            if isinstance(item, str) and (text := _clean(item, MAX_CHOICE_CHARS)):
                choices.append(text)
    return {"question": question, "choices": choices}
