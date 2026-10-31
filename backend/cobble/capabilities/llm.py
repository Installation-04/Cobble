"""LLM capability: send a chat request for a role. Implemented by the cost router."""

from __future__ import annotations

import enum
import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Protocol


class Role(enum.StrEnum):
    """Model roles. Each role maps to a model in the configuration."""

    PLANNER = "planner"
    TEST_WRITER = "test-writer"
    WORKER = "worker"
    REVIEWER = "reviewer"


@dataclass(frozen=True)
class ChatResult:
    content: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    cost_usd: Decimal
    request_id: str | None


class LLMClient(Protocol):
    def chat(
        self,
        role: Role,
        messages: list[dict[str, Any]],
        *,
        project_id: uuid.UUID | None = None,
        task_id: uuid.UUID | None = None,
    ) -> ChatResult: ...
