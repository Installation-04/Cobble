"""Lessons learned inside a project (ADR 0026).

When a task keeps failing, the failure signal (the first failing test and its message, the line an
agent kept repeating, the last output before a timeout) is turned into one short, redacted
sentence and stored for the project. The most useful ones are added to the prompts of later
agents of the same project so they stop repeating the mistake. Everything here is deterministic:
no model is called, and a lesson is at most `MAX_TEXT` characters, so the cost of the prompt
block is bounded (`INJECT_CHARS` characters, about 300 tokens, and nothing when there is none).
"""

from __future__ import annotations

import logging
import re
import uuid
from collections import Counter

from sqlalchemy import select
from sqlalchemy.orm import Session

from cobble.db import ProjectLesson, Task

log = logging.getLogger(__name__)

CI_FAILURE = "ci_failure"
LOOP = "loop"
TIMEOUT = "timeout"
MANUAL = "manual"
SOURCES = (CI_FAILURE, LOOP, TIMEOUT, MANUAL)

MAX_TEXT = 300
MAX_ACTIVE = 20  # active lessons per project; beyond it the least useful captured one is dropped
INJECT_MAX = 5  # lessons shown to an agent
INJECT_CHARS = 1200  # upper bound of the block (about 300 tokens)
MAX_LINE = 160  # a log line quoted in a lesson

_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
_KEYED_SECRET = re.compile(
    r"(?i)\b(token|secret|password|passwd|api[_-]?key|apikey|authorization)\b(\s*[:=]\s*)\S+"
)
_BEARER = re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}")
_PREFIXED = re.compile(r"\b(?:sk|ghp|gho|ghs|github_pat|glpat|xox[abp])[-_][A-Za-z0-9_-]{8,}")
_URL_CREDENTIALS = re.compile(r"://[^/\s:@]+:[^/\s@]+@")
_LONG_TOKEN = re.compile(r"[A-Za-z0-9_\-+=]{32,}")
_PYTEST_FAILED = re.compile(r"^\s*FAILED\s+(\S+)(?:\s+-\s+(.*))?$")
_JS_FAILED = re.compile(r"^\s*FAIL\s+(.+?)\s*$")
_ERROR_LINE = re.compile(r"^\s*(?:E\s+)?(.*(?:Error|Exception|assert|expected).*)$", re.IGNORECASE)


def _mask_long(match: re.Match[str]) -> str:
    token = match.group(0)
    looks_secret = (
        any(c.isdigit() for c in token) and any(c.isalpha() for c in token)
    ) and token.count("_") < 3
    return "***" if looks_secret else token


def redact(text: str) -> str:
    """Mask what looks like a credential (keyed values, bearer tokens, vendor prefixes, long
    random tokens, passwords in URLs). Best effort: lessons also stay short and are only ever
    shown to the project owner and to the project's own agents."""
    text = _ANSI.sub("", text)
    text = _URL_CREDENTIALS.sub("://***@", text)
    text = _BEARER.sub(r"\1 ***", text)
    text = _KEYED_SECRET.sub(r"\1\2***", text)
    text = _PREFIXED.sub("***", text)
    return _LONG_TOKEN.sub(_mask_long, text)


def _squash(text: str) -> str:
    return " ".join(text.split())


def clip(text: str, limit: int = MAX_TEXT) -> str:
    text = _squash(text)
    return text if len(text) <= limit else text[: limit - 3].rstrip() + "..."


def _lines(log_text: str) -> list[str]:
    return [line for line in (_squash(redact(x)) for x in log_text.splitlines()) if line]


def _compose(prefix: str, detail: str, suffix: str) -> str:
    room = MAX_TEXT - len(prefix) - len(suffix)
    return prefix + clip(detail, max(room, 20)) + suffix


def signal_from_ci(detail: str) -> str | None:
    """The first failing test and its message from a CI log, or None when there is no such signal
    (a timeout or a refused merge teaches nothing about the code)."""
    lines = _lines(detail)
    for index, line in enumerate(lines):
        match = _PYTEST_FAILED.match(line)
        message: str | None = match.group(2) if match else None
        js = None if match else _JS_FAILED.match(line)
        found_name = match or js
        if found_name is None:
            continue
        name = found_name.group(1)
        if not message:
            for later in lines[index + 1 : index + 12]:
                found = _ERROR_LINE.match(later)
                if found:
                    message = found.group(1)
                    break
        if message:
            return _compose(
                f"CI failed on {clip(name, 100)}: ", message, ". Check it before finishing."
            )
        return _compose("CI failed on ", name, ". Check it before finishing.")
    for line in lines:
        found = _ERROR_LINE.match(line)
        if found:
            return _compose("CI failed: ", found.group(1), ". Check it before finishing.")
    return None


def signal_from_loop(log_text: str) -> str | None:
    """The line an agent kept repeating (or, failing that, its last line)."""
    lines = [clip(x, MAX_LINE) for x in _lines(log_text)]
    if not lines:
        return None
    line, count = Counter(lines).most_common(1)[0]
    if count >= 2:
        return _compose(
            "An agent got stuck repeating: ", line, ". Change approach instead of retrying."
        )
    return _compose("An agent got stuck; its last output was: ", lines[-1], ".")


def signal_from_timeout(log_text: str) -> str | None:
    """The last output before a run ran out of time."""
    lines = [clip(x, MAX_LINE) for x in _lines(log_text)]
    if not lines:
        return None
    return _compose(
        "A run timed out; its last output was: ",
        lines[-1],
        ". Work in smaller steps and avoid long-running commands.",
    )


def _key(text: str) -> str:
    """What two lessons must share to be the same: case, digits and spacing do not matter."""
    return re.sub(r"\d+", "#", _squash(text).lower())


def _active(session: Session, project_id: uuid.UUID) -> list[ProjectLesson]:
    stmt = select(ProjectLesson).where(
        ProjectLesson.project_id == project_id, ProjectLesson.active.is_(True)
    )
    return list(session.scalars(stmt))


def _usefulness(lesson: ProjectLesson) -> tuple[int, float]:
    return (lesson.hits, lesson.created_at.timestamp() if lesson.created_at else 0.0)


def active_count(session: Session, project_id: uuid.UUID) -> int:
    return len(_active(session, project_id))


def record(
    session: Session,
    project_id: uuid.UUID,
    text: str,
    source: str,
    task_ref: str | None = None,
) -> ProjectLesson | None:
    """Store a lesson (flushed, not committed). A lesson already known only gains a hit.

    Over the cap, the least useful captured lesson (fewest hits, then oldest) is deleted; manual
    lessons are never dropped, so when only manual ones remain the new lesson is refused (None).
    """
    text = clip(redact(text))
    if not text:
        return None
    key = _key(text)
    rows = list(
        session.scalars(select(ProjectLesson).where(ProjectLesson.project_id == project_id))
    )
    for row in rows:
        if _key(row.text) == key:
            row.hits += 1
            session.flush()
            return row
    lesson = ProjectLesson(
        project_id=project_id, text=text, source=source, task_ref=task_ref, hits=1, active=True
    )
    session.add(lesson)
    session.flush()
    active = [r for r in rows if r.active] + [lesson]
    while len(active) > MAX_ACTIVE:
        droppable = sorted((r for r in active if r.source != MANUAL), key=_usefulness)
        if not droppable:
            session.delete(lesson)
            session.flush()
            return None
        victim = droppable[0]
        active.remove(victim)
        session.delete(victim)
        if victim is lesson:
            session.flush()
            return None
    session.flush()
    return lesson


def capture_failure(
    session: Session, task: Task, source: str, detail: str | None, min_attempts: int
) -> None:
    """Learn from a failed attempt of `task`, once the task has failed `min_attempts` times (a
    first failure is usually fixed by the next attempt and would only add noise). Never raises:
    a lesson must not break the scheduler."""
    if not detail or task.kind == "revert" or task.attempts < min_attempts:
        return
    signal = {
        CI_FAILURE: signal_from_ci,
        LOOP: signal_from_loop,
        TIMEOUT: signal_from_timeout,
    }.get(source)
    if signal is None:
        return
    try:
        text = signal(detail)
        if text:
            with session.begin_nested():
                record(session, task.project_id, text, source, task.ref)
    except Exception:
        log.warning("could not record a lesson for %s", task.ref, exc_info=True)


def injected(session: Session, project_id: uuid.UUID) -> list[ProjectLesson]:
    """The lessons the next agent will see: active, most hit first, then most recent."""
    rows = sorted(_active(session, project_id), key=_usefulness, reverse=True)
    chosen: list[ProjectLesson] = []
    used = 0
    for row in rows[:INJECT_MAX]:
        used += len(row.text) + 3
        if used > INJECT_CHARS:
            break
        chosen.append(row)
    return chosen


def prompt_block(session: Session, project_id: uuid.UUID) -> str:
    """The short block added to the prompts; empty when the project has no active lesson."""
    rows = injected(session, project_id)
    if not rows:
        return ""
    bullets = "\n".join(f"- {row.text}" for row in rows)
    return (
        "\nLessons from this project (mistakes already made here; do not repeat them):\n"
        f"{bullets}\n"
    )
