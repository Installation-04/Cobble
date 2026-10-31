"""Prompt builders for the planner. Pure and deterministic: same input, same messages.

Prompts are English. The planner is told to answer in the user's language. Because the fake
LLM cassettes are keyed by the exact messages, changing any text here means regenerating them
(see providers/fake-llm/README.md).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

Message = dict[str, Any]

LANGUAGES = {"fr": "French", "en": "English"}
MAX_PLAN_ATTEMPTS = 3  # first try + 2 automatic retries

STACK = (
    "The only project template available is a FastAPI backend (Python) with a simple web "
    "front end. Never propose another stack."
)

INTERVIEW_SYSTEM = (
    "You are the planner of Cobble, a platform that turns an idea into a working application. "
    "You are interviewing a person who is probably not technical.\n"
    "Rules:\n"
    "- Reply in {language}, the user's language.\n"
    "- Ask targeted questions instead of guessing: audience, main features, data to keep, "
    "platform, constraints. Ask at most 3 questions per message.\n"
    "- Propose a simple stack. " + STACK + "\n"
    "- Keep every answer short: at most 120 words, plain words, no jargon.\n"
    "- When you have enough information, say that the user can generate the specification."
)

SPEC_SYSTEM = (
    "You are the planner of Cobble. From the interview below, write the specification of the "
    "application.\n"
    "Rules:\n"
    "- Write in {language}, the user's language.\n"
    "- Reply with the Markdown document only, with no text before or after it.\n"
    "- Start with a level-1 title (the application name), then a short summary, then these "
    "level-2 sections in this order: Features, Screens, Data model, Constraints, Out of scope.\n"
    "- Be concrete and testable. Do not invent features the user did not ask for.\n"
    "- " + STACK
)

PLAN_SYSTEM = (
    "You are the planner of Cobble. Turn the approved specification into an implementation "
    "plan for small coding agents.\n"
    "Reply with ONLY one JSON object: no commentary, no Markdown outside an optional ```json "
    "fence.\n"
    "Schema:\n"
    '{{"milestones": [{{"id": "M1", "title": "..."}}], "tasks": [{{"id": "T-001", '
    '"title": "...", "milestone": "M1", "depends_on": [], "files": ["app/main.py", '
    '"tests/test_main.py"], "acceptance": ["..."], "tests": "tests/test_main.py", '
    '"size": "S", "role": "backend"}}]}}\n'
    "Rules:\n"
    "- Use at most 3 milestones (ids M1, M2, ...), each one a demo the user can try. Tasks are "
    "numbered T-001, T-002, ...\n"
    '- "size" is "S" or "M", never "L": split anything bigger into several tasks.\n'
    '- "role" is one of backend, frontend, fullstack, devops, docs.\n'
    '- "acceptance": one to four testable criteria per task (an observable behaviour, for '
    "example an HTTP status or a visible result). Write them in English.\n"
    '- "tests": the path of the test file, written BEFORE the implementation, so it must '
    'also be listed in "files".\n'
    '- "files": relative paths only (backend in app/, tests in tests/, front end in web/), '
    "never absolute and never containing '..'. Keep tasks from sharing files when possible.\n"
    '- "depends_on": ids of tasks that must be finished first; no cycles; every id must exist.\n'
    "- Write milestone and task titles in {language}, the user's language.\n"
    "- " + STACK
)


def language_name(lang: str) -> str:
    return LANGUAGES.get(lang, "English")


def _fill(template: str, lang: str) -> str:
    return template.format(language=language_name(lang))


def _transcript(history: Sequence[Message]) -> str:
    return "\n\n".join(f"[{m['role']}] {m['content']}" for m in history)


def interview_messages(history: Sequence[Message], lang: str) -> list[Message]:
    """System prompt followed by the whole conversation, oldest first."""
    return [
        {"role": "system", "content": _fill(INTERVIEW_SYSTEM, lang)},
        *({"role": m["role"], "content": m["content"]} for m in history),
    ]


def spec_messages(
    history: Sequence[Message],
    lang: str,
    *,
    feedback: str | None = None,
    previous_spec: str | None = None,
) -> list[Message]:
    parts = ["Interview:\n\n" + _transcript(history)]
    if feedback and previous_spec:
        parts.append("Previous specification:\n\n" + previous_spec)
        parts.append("The user asks for these changes:\n\n" + feedback)
        parts.append("Write the full updated specification now.")
    else:
        parts.append("Write the specification now.")
    return [
        {"role": "system", "content": _fill(SPEC_SYSTEM, lang)},
        {"role": "user", "content": "\n\n".join(parts)},
    ]


def plan_messages(
    spec: str,
    lang: str,
    *,
    feedback: str | None = None,
    previous_plan: str | None = None,
) -> list[Message]:
    parts = ["Approved specification:\n\n" + spec]
    if feedback and previous_plan:
        parts.append("Previous plan:\n\n" + previous_plan)
        parts.append("The user asks for these changes:\n\n" + feedback)
        parts.append("Return the full updated JSON plan now.")
    else:
        parts.append("Return the JSON plan now.")
    return [
        {"role": "system", "content": _fill(PLAN_SYSTEM, lang)},
        {"role": "user", "content": "\n\n".join(parts)},
    ]


def retry_messages(
    messages: Sequence[Message], raw_reply: str, errors: Sequence[str]
) -> list[Message]:
    """Extend a plan conversation with the rejected reply and the errors to fix."""
    listing = "\n".join(f"- {error}" for error in errors)
    return [
        *messages,
        {"role": "assistant", "content": raw_reply},
        {
            "role": "user",
            "content": (
                "Your plan was rejected for these reasons:\n"
                f"{listing}\n"
                "Return the corrected JSON plan only."
            ),
        },
    ]
