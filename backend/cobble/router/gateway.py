"""Gateway to LiteLLM: sends chat requests and records tokens and cost per call.

All LLM calls go through LiteLLM (never a provider SDK). The cost router
(`cobble/router/costs.py`) wraps this gateway to implement the `LLMClient` capability.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx
from redis import Redis
from sqlalchemy.orm import Session, sessionmaker

from cobble.capabilities.llm import ChatResult
from cobble.db import LLMCall
from cobble.events import publish

COST_HEADER = "x-litellm-response-cost"
CALL_ID_HEADER = "x-litellm-call-id"


__all__ = ["ChatResult", "GatewayError", "LiteLLMGateway", "ProbeResult"]


@dataclass(frozen=True)
class ProbeResult:
    """Can the gateway reach this model with its key? `code` is one of a few stable values;
    the provider's own error text is never kept (it can quote part of the key)."""

    ok: bool
    code: str  # ok | auth_failed | model_not_found | rate_limited | unreachable | failed


class GatewayError(RuntimeError):
    def __init__(self, status: int) -> None:
        super().__init__(f"model gateway returned HTTP {status}")
        self.status = status


def _cost(headers: httpx.Headers) -> Decimal:
    try:
        return Decimal(headers.get(COST_HEADER, "0"))
    except InvalidOperation:
        return Decimal(0)


_PROBE_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "auth_failed",
        (
            "authentication",
            "unauthorized",
            "invalid api key",
            "incorrect api key",
            "401",
            "403",
            "permission",
        ),
    ),
    ("model_not_found", ("model_not_found", "not found", "does not exist", "unknown model", "404")),
    (
        "rate_limited",
        ("ratelimit", "rate limit", "rate_limit", "quota", "insufficient", "429", "billing"),
    ),
    ("unreachable", ("timeout", "timed out", "connection", "resolve", "unreachable", "refused")),
)


def classify_probe(status: int, body: object) -> ProbeResult:
    """Map the gateway's health answer to a stable code, without relaying any of its text."""
    if not isinstance(body, dict):
        return ProbeResult(False, "failed")  # not an answer of the gateway's health check
    data = body
    if int(data.get("healthy_count") or 0) > 0:
        return ProbeResult(True, "ok")
    unhealthy = data.get("unhealthy_endpoints") or []
    if not unhealthy:
        # The gateway does not know the model at all (it answers 503 with nothing listed).
        return ProbeResult(False, "model_not_found")
    text = " ".join(
        str(entry.get("error", "")) for entry in unhealthy if isinstance(entry, dict)
    ).lower()
    for code, needles in _PROBE_PATTERNS:
        if any(needle in text for needle in needles):
            return ProbeResult(False, code)
    return ProbeResult(False, "failed")


class LiteLLMGateway:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        sessions: sessionmaker[Session],
        events: Redis | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self._sessions = sessions
        self._events = events
        self._client = client or httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {api_key}"} if api_key else {},
            timeout=120.0,
        )

    def probe(self, model: str) -> ProbeResult:
        """Ask the gateway to check one model with its own health check (a one-token request
        made by the gateway itself, not a task: it is not recorded in any project's costs)."""
        try:
            reply = self._client.get("/health", params={"model": model}, timeout=90.0)
        except httpx.HTTPError:
            return ProbeResult(False, "unreachable")
        try:
            body = reply.json()
        except ValueError:
            body = None
        if reply.status_code in (401, 403) and not isinstance(body, dict):
            return ProbeResult(False, "failed")  # the platform's own key to the gateway is wrong
        return classify_probe(reply.status_code, body)

    def chat(
        self,
        model: str,
        messages: list[dict[str, Any]],
        *,
        role: str | None = None,
        project_id: uuid.UUID | None = None,
        task_id: uuid.UUID | None = None,
    ) -> ChatResult:
        reply = self._client.post(
            "/v1/chat/completions", json={"model": model, "messages": messages}
        )
        if reply.status_code != 200:
            raise GatewayError(reply.status_code)
        data = reply.json()
        usage = data.get("usage") or {}
        result = ChatResult(
            content=data["choices"][0]["message"].get("content") or "",
            model=data.get("model", model),
            prompt_tokens=int(usage.get("prompt_tokens", 0)),
            completion_tokens=int(usage.get("completion_tokens", 0)),
            cost_usd=_cost(reply.headers),
            request_id=reply.headers.get(CALL_ID_HEADER) or data.get("id"),
        )
        call_id = uuid.uuid4()
        with self._sessions() as session:
            session.add(
                LLMCall(
                    id=call_id,
                    model=result.model,
                    role=role,
                    project_id=project_id,
                    task_id=task_id,
                    prompt_tokens=result.prompt_tokens,
                    completion_tokens=result.completion_tokens,
                    cost_usd=result.cost_usd,
                    request_id=result.request_id,
                )
            )
            session.commit()
        if self._events is not None:
            publish(
                self._events,
                "llm.call.completed",
                {
                    "id": str(call_id),
                    "model": result.model,
                    "role": role,
                    "project_id": str(project_id) if project_id else None,
                    "task_id": str(task_id) if task_id else None,
                    "prompt_tokens": result.prompt_tokens,
                    "completion_tokens": result.completion_tokens,
                    "cost_usd": str(result.cost_usd),
                },
            )
        return result
