"""Cost router: maps a role to a model, enforces the project budget, calls the gateway."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping
from typing import Any, Protocol

from cobble.capabilities.llm import ChatResult, Role

from .budget import BudgetService


class ChatGateway(Protocol):
    def chat(
        self,
        model: str,
        messages: list[dict[str, Any]],
        *,
        role: str | None = None,
        project_id: uuid.UUID | None = None,
        task_id: uuid.UUID | None = None,
    ) -> ChatResult: ...


class CostRouter:
    """Implements the `LLMClient` capability."""

    def __init__(
        self,
        gateway: ChatGateway,
        budget: BudgetService,
        role_models: Mapping[str, str],
        default_model: str | Callable[[], str],
    ) -> None:
        self._gateway = gateway
        self._budget = budget
        self._role_models = dict(role_models)
        # A callable lets the default change while the process runs (see `ModelPolicy`).
        self._default_model: Callable[[], str] = (
            default_model if callable(default_model) else (lambda: default_model)
        )

    def model_for(self, role: Role) -> str:
        return self._role_models.get(role.value) or self._default_model()

    def chat(
        self,
        role: Role,
        messages: list[dict[str, Any]],
        *,
        project_id: uuid.UUID | None = None,
        task_id: uuid.UUID | None = None,
        model: str | None = None,
    ) -> ChatResult:
        """`model` overrides the role's model (used for escalation); callers must be trusted."""
        if project_id is not None:
            self._budget.ensure_can_spend(project_id)  # raises BudgetExceeded
        result = self._gateway.chat(
            model or self.model_for(role),
            messages,
            role=role.value,
            project_id=project_id,
            task_id=task_id,
        )
        if project_id is not None:
            self._budget.after_call(project_id)
        return result
