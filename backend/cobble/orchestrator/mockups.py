"""Mockup variants (ADR 0018): prompts, strict parsing and sanitising of the planner's answer.

A mockup is plain text: a title, a short summary and an ASCII wireframe. The model is never
asked for HTML, and anything it sends is stored and shown as inert text (the UI renders it in a
`<pre>` as escaped text), so no model-provided markup or script can ever run. Pure functions,
no I/O.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from .plan_schema import PlanInvalid, extract_json
from .prompts import STACK, Message, language_name

MIN_VARIANTS = 2
MAX_VARIANTS = 3
MAX_MOCKUP_ATTEMPTS = 2  # first try + 1 automatic retry
TITLE_MAX = 120
SUMMARY_MAX = 600
WIREFRAME_MAX_LINES = 30
WIREFRAME_MAX_COLS = 80

MOCKUPS_SYSTEM = (
    "You are the planner of Cobble. From the approved specification below, propose {count} "
    "clearly DIFFERENT mockups of the main screen of the application, so that the user can "
    "choose a direction before any code is written.\n"
    "Reply with ONLY one JSON object: no commentary, no Markdown outside an optional ```json "
    "fence.\n"
    "Schema:\n"
    '{{"variants": [{{"title": "...", "summary": "...", "wireframe": "..."}}]}}\n'
    "Rules:\n"
    "- Exactly {count} variants, each with a different layout or interaction idea.\n"
    '- "title": at most 6 words. "summary": at most 2 sentences about what makes this '
    "variant different.\n"
    '- "wireframe": a plain-text ASCII drawing of the screen (boxes with + - |, at most '
    + str(WIREFRAME_MAX_LINES)
    + " lines of "
    + str(WIREFRAME_MAX_COLS)
    + " characters). Plain text only: never HTML, CSS, scripts or Markdown.\n"
    "- Write the title and summary in {language}, the user's language. Never invent features "
    "the specification does not contain.\n"
    "- " + STACK
)


class MockupsInvalid(PlanInvalid):
    """The planner's mockups break at least one rule."""


@dataclass(frozen=True)
class ParsedVariant:
    title: str
    summary: str
    wireframe: str


# Control characters other than newline; tabs become spaces.
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


def _clean(value: str) -> str:
    return _CONTROL.sub("", value.replace("\r\n", "\n").replace("\r", "\n").replace("\t", "    "))


def _wireframe(value: str) -> str:
    lines = [line.rstrip()[:WIREFRAME_MAX_COLS] for line in _clean(value).split("\n")]
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines[:WIREFRAME_MAX_LINES])


def mockup_messages(
    spec: str, lang: str, count: int, *, feedback: str | None = None
) -> list[Message]:
    count = max(MIN_VARIANTS, min(MAX_VARIANTS, count))
    parts = ["Approved specification:\n\n" + spec]
    if feedback:
        parts.append("The user asks for these changes to the mockups:\n\n" + feedback)
    parts.append("Return the JSON with the mockup variants now.")
    system = MOCKUPS_SYSTEM.format(language=language_name(lang), count=count)
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": "\n\n".join(parts)},
    ]


def mockup_retry_messages(
    messages: Sequence[Message], raw_reply: str, errors: Sequence[str]
) -> list[Message]:
    listing = "\n".join(f"- {error}" for error in errors)
    return [
        *messages,
        {"role": "assistant", "content": raw_reply},
        {
            "role": "user",
            "content": (
                f"Your mockups were rejected for these reasons:\n{listing}\n"
                "Return the corrected JSON only."
            ),
        },
    ]


def parse_mockups(text: str, count: int) -> list[ParsedVariant]:
    """Validate and sanitise a planner reply. Raises `MockupsInvalid`."""
    try:
        data: Any = extract_json(text)
    except PlanInvalid as exc:
        raise MockupsInvalid(exc.errors) from None
    raw = data.get("variants") if isinstance(data, dict) else None
    if not isinstance(raw, list):
        raise MockupsInvalid(['"variants" must be a list'])
    errors: list[str] = []
    variants: list[ParsedVariant] = []
    for index, item in enumerate(raw, start=1):
        if not isinstance(item, dict) or not all(
            isinstance(item.get(key), str) for key in ("title", "summary", "wireframe")
        ):
            errors.append(f"variant {index}: title, summary and wireframe must be strings")
            continue
        title = " ".join(_clean(item["title"]).split())[:TITLE_MAX]
        summary = " ".join(_clean(item["summary"]).split())[:SUMMARY_MAX]
        wireframe = _wireframe(item["wireframe"])
        if not title or not wireframe:
            errors.append(f"variant {index}: title and wireframe must not be empty")
            continue
        variants.append(ParsedVariant(title, summary, wireframe))
    if errors:
        raise MockupsInvalid(errors)
    if len(variants) < MIN_VARIANTS:
        raise MockupsInvalid([f"at least {MIN_VARIANTS} variants are required"])
    return variants[: max(MIN_VARIANTS, min(MAX_VARIANTS, count))]


def mockup_context(title: str, summary: str, wireframe: str) -> str:
    """The chosen variant, as it is given to the plan prompt."""
    return f"{title}\n{summary}\n\n{wireframe}"
