"""Cost router: maps a role to models, enforces the project budget, calls the gateway.

A role has an ordered chain of models. The first one answers unless it cannot (the service
refuses the key, is out of balance or rate limited, does not know the model, is down): then the
next one is tried, and the call that finally answered says which model it was. A request the
service itself rejects as malformed (HTTP 400) is the same for every model and is not retried.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Callable, Mapping
from typing import Any, Protocol

import httpx

from cobble.capabilities.llm import ChatResult, Role

from .budget import BudgetService
from .gateway import GatewayError

log = logging.getLogger(__name__)


class LocalOnlyUnavailable(Exception):
    """The project may only use models served on this machine, and none can answer."""

    def __init__(self, project_id: uuid.UUID) -> None:
        super().__init__(f"project {project_id} is local-only and no local model is available")
        self.project_id = project_id


# Statuses that mean "this model cannot answer right now", not "this request is wrong".
FALLBACK_STATUSES = frozenset({401, 402, 403, 404, 408, 429}) | frozenset(range(500, 600))


class RateLimitBackoff:
    """Leaves a model alone for a while after it answered 429 (rate limited).

    The wait doubles at each consecutive refusal (`base_s`, 2x, 4x... up to `max_s`) and is
    forgotten at the first answer. A model cooling down is not removed from the owner's chain:
    it is tried after the others for the duration (the call still goes to it when nothing else
    is left). Free tiers are the usual case: their limits are low and strict (ADR 0013)."""

    def __init__(
        self,
        base_s: float = 30.0,
        max_s: float = 600.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._base_s = base_s
        self._max_s = max_s
        self._clock = clock
        self._until: dict[str, float] = {}
        self._strikes: dict[str, int] = {}

    def hit(self, model: str) -> None:
        strikes = self._strikes.get(model, 0) + 1
        self._strikes[model] = strikes
        self._until[model] = self._clock() + min(self._base_s * 2 ** (strikes - 1), self._max_s)

    def ok(self, model: str) -> None:
        self._strikes.pop(model, None)
        self._until.pop(model, None)

    def cooling(self, model: str) -> bool:
        return self._until.get(model, 0.0) > self._clock()

    def order(self, candidates: list[str]) -> list[str]:
        """The same models, those cooling down last (the relative order is kept)."""
        ready = [m for m in candidates if not self.cooling(m)]
        return ready + [m for m in candidates if self.cooling(m)]


# Shared by every router of the process, so the memory of a 429 outlives one request.
SHARED_BACKOFF = RateLimitBackoff()


class ChatGateway(Protocol):
    def chat(
        self,
        model: str,
        messages: list[dict[str, Any]],
        *,
        role: str | None = None,
        project_id: uuid.UUID | None = None,
        task_id: uuid.UUID | None = None,
        fallback_from: str | None = None,
        fallbacks: int = 0,
    ) -> ChatResult: ...


def can_fall_back(error: Exception) -> bool:
    if isinstance(error, GatewayError):
        return error.status in FALLBACK_STATUSES or error.unknown_model
    return isinstance(error, httpx.TransportError)  # unreachable, timeout, reset


class CostRouter:
    """Implements the `LLMClient` capability."""

    def __init__(
        self,
        gateway: ChatGateway,
        budget: BudgetService,
        role_models: Mapping[str, str],
        default_model: str | Callable[[], str],
        chain_for: Callable[[Role], list[str]] | None = None,
        is_local_only: Callable[[uuid.UUID], bool] | None = None,
        local_models: Callable[[], set[str]] | None = None,
        backoff: RateLimitBackoff | None = None,
    ) -> None:
        self._backoff = backoff or RateLimitBackoff()
        self._gateway = gateway
        self._budget = budget
        self._role_models = dict(role_models)
        # A callable lets the default change while the process runs (see `ModelPolicy`).
        self._default_model: Callable[[], str] = (
            default_model if callable(default_model) else (lambda: default_model)
        )
        self._chain_for = chain_for
        self._is_local_only = is_local_only
        self._local_models = local_models

    def chain_for(self, role: Role) -> list[str]:
        if self._chain_for is not None:
            return self._chain_for(role)
        return [self._role_models.get(role.value) or self._default_model()]

    def model_for(self, role: Role) -> str:
        return self.chain_for(role)[0]

    def chat(
        self,
        role: Role,
        messages: list[dict[str, Any]],
        *,
        project_id: uuid.UUID | None = None,
        task_id: uuid.UUID | None = None,
        model: str | None = None,
    ) -> ChatResult:
        """`model` goes first (used for escalation: callers must be trusted); the role's
        chain follows as fallbacks."""
        if project_id is not None:
            self._budget.ensure_can_spend(project_id, task_id)  # raises BudgetExceeded
        candidates = self.chain_for(role)
        if model is not None:
            candidates = [model, *(m for m in candidates if m != model)]
        if (
            project_id is not None
            and self._is_local_only is not None
            and self._is_local_only(project_id)
        ):
            # Confidential project: only models served here, whatever the route or the
            # escalation asks for. Unknown or unreachable local models mean none: fail closed.
            local = self._local_models() if self._local_models is not None else set()
            candidates = [m for m in candidates if m in local]
            if not candidates:
                raise LocalOnlyUnavailable(project_id)
        result = self._first_answer(candidates, role, messages, project_id, task_id)
        if project_id is not None:
            self._budget.after_call(project_id)
        return result

    def _first_answer(
        self,
        candidates: list[str],
        role: Role,
        messages: list[dict[str, Any]],
        project_id: uuid.UUID | None,
        task_id: uuid.UUID | None,
    ) -> ChatResult:
        last: Exception | None = None
        failed: list[str] = []
        ordered = self._backoff.order(candidates)
        if ordered != candidates:
            log.info("rate-limited models are tried last for now: %s", candidates)
            candidates = ordered
        for index, candidate in enumerate(candidates):
            try:
                if not failed:  # the usual case: the call is exactly what it always was
                    result = self._gateway.chat(
                        candidate, messages, role=role.value, project_id=project_id, task_id=task_id
                    )
                else:
                    result = self._gateway.chat(
                        candidate,
                        messages,
                        role=role.value,
                        project_id=project_id,
                        task_id=task_id,
                        fallback_from=failed[0],
                        fallbacks=len(failed),
                    )
                self._backoff.ok(candidate)
                return result
            except Exception as error:
                if not can_fall_back(error):
                    raise
                if isinstance(error, GatewayError) and error.status == 429:
                    self._backoff.hit(candidate)
                last = error
                failed.append(candidate)
                if index + 1 < len(candidates):
                    log.warning(
                        "model %s cannot answer for %s, trying %s",
                        candidate,
                        role.value,
                        candidates[index + 1],
                    )
        if last is None:  # unreachable: the chain is never empty
            raise RuntimeError("no model to try")
        raise last
