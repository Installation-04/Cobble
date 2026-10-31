"""Helpers shared by the interview / spec / plan tests."""

from __future__ import annotations

import importlib.util
import json
import uuid
from pathlib import Path
from types import ModuleType
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from cobble.capabilities.llm import ChatResult, Role
from cobble.db import Project, User
from cobble.events import project_stream

from .fakes import FakeStreamRedis

REPO = Path(__file__).resolve().parents[3]
SCRIPT = REPO / "providers" / "fake-llm" / "scripts" / "make_todo_cassettes.py"
CASSETTES = REPO / "providers" / "fake-llm" / "cassettes"


def load_script() -> ModuleType:
    """The cassette generator, which also holds the scripted to-do flow."""
    spec = importlib.util.spec_from_file_location("make_todo_cassettes", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ScriptedLLM:
    """`LLMClient` returning queued replies (or raising queued exceptions), recording calls."""

    def __init__(self, *replies: str | Exception) -> None:
        self.replies = list(replies)
        self.calls: list[list[dict[str, Any]]] = []

    def chat(
        self,
        role: Role,
        messages: list[dict[str, Any]],
        *,
        project_id: uuid.UUID | None = None,
        task_id: uuid.UUID | None = None,
    ) -> ChatResult:
        assert role is Role.PLANNER
        self.calls.append(messages)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return ChatResult(reply, "fake", 1, 1, 0, None)  # type: ignore[arg-type]


def make_project(
    sessions: sessionmaker[Session], *, lang: str = "en", phase: str = "interview"
) -> uuid.UUID:
    with sessions() as db:
        user = User(email=f"{uuid.uuid4().hex[:8]}@example.com", password_hash="x", lang=lang)
        db.add(user)
        db.flush()
        project = Project(owner_id=user.id, name="Todo", phase=phase)
        db.add(project)
        db.commit()
        return project.id


def events_of(redis: FakeStreamRedis, project_id: uuid.UUID) -> list[tuple[str, dict[str, Any]]]:
    return [
        (e["type"], json.loads(e["payload"])) for e in redis.entries(project_stream(project_id))
    ]
