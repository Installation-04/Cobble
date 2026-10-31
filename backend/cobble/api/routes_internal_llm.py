"""Internal LLM endpoint used by coding agents.

OpenAI-compatible, non-streaming. Not routed by the public reverse proxy: only the internal
networks reach it. Authenticated with a signed per-run token (see cobble.auth.runtoken). Every
call goes through the cost router, so the project budget applies and tokens/cost are recorded
with the project and task, exactly like the planner's calls.
"""

from __future__ import annotations

import time
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Header, Request

from cobble.auth import runtoken
from cobble.capabilities.llm import Role
from cobble.router.budget import BudgetExceeded
from cobble.router.factory import build_cost_router
from cobble.router.gateway import GatewayError

from .errors import ApiError

router = APIRouter()

_ALLOWED_KEYS = ("role", "content", "name")


def _claims(request: Request, authorization: str | None) -> runtoken.RunClaims:
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise ApiError(401, "invalid_token")
    try:
        return runtoken.verify(request.app.state.settings.run_token_secret, token)
    except runtoken.InvalidRunToken:
        raise ApiError(401, "invalid_token") from None


def _cost_router(request: Request) -> Any:
    state = request.app.state
    if getattr(state, "cost_router", None) is None:
        state.cost_router = build_cost_router(state.settings, state.session_factory, state.redis)
    return state.cost_router


@router.post("/internal/llm/v1/chat/completions")
def chat_completions(
    body: dict[str, Any],
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
) -> dict[str, Any]:
    claims = _claims(request, authorization)
    messages = body.get("messages")
    if not isinstance(messages, list) or not messages:
        raise ApiError(422, "validation_error", fields=["messages"])
    if body.get("stream"):
        raise ApiError(400, "streaming_unsupported")
    try:
        role = Role(claims.role)
    except ValueError:
        raise ApiError(401, "invalid_token") from None
    clean = [
        {k: v for k, v in message.items() if k in _ALLOWED_KEYS}
        for message in messages
        if isinstance(message, dict)
    ]
    try:
        # The model comes from the token (role mapping or the scheduler's escalation), never
        # from the request body.
        result = _cost_router(request).chat(
            role,
            clean,
            project_id=claims.project_id,
            task_id=claims.task_id,
            model=claims.model_override,
        )
    except BudgetExceeded:
        raise ApiError(402, "budget_reached") from None
    except GatewayError:
        raise ApiError(502, "llm_error") from None
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:24]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": result.model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": result.content},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": result.prompt_tokens,
            "completion_tokens": result.completion_tokens,
            "total_tokens": result.prompt_tokens + result.completion_tokens,
        },
    }
