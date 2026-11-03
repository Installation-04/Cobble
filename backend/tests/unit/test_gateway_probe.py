"""Testing a model connection through the gateway: stable codes, never the provider's words."""

from __future__ import annotations

import httpx
import pytest
from sqlalchemy.orm import Session, sessionmaker

from cobble.router.gateway import LiteLLMGateway, ProbeResult, classify_probe

LEAKY = "AuthenticationError: Incorrect API key provided: sk-live-abcdef1234567890. 401"


def healthy() -> dict[str, object]:
    return {
        "healthy_endpoints": [{"model": "openai/x"}],
        "unhealthy_endpoints": [],
        "healthy_count": 1,
    }


def unhealthy(error: str) -> dict[str, object]:
    return {
        "healthy_endpoints": [],
        "unhealthy_endpoints": [{"model": "openai/x", "error": error}],
        "healthy_count": 0,
        "unhealthy_count": 1,
    }


@pytest.mark.parametrize(
    ("status", "body", "expected"),
    [
        (200, healthy(), ProbeResult(True, "ok")),
        (
            503,
            {"healthy_endpoints": [], "unhealthy_endpoints": [], "healthy_count": 0},
            ProbeResult(False, "model_not_found"),
        ),
        (200, unhealthy(LEAKY), ProbeResult(False, "auth_failed")),
        (
            200,
            unhealthy("litellm.RateLimitError: You exceeded your current quota"),
            ProbeResult(False, "rate_limited"),
        ),
        (
            200,
            unhealthy("NotFoundError: The model `gpt-9` does not exist"),
            ProbeResult(False, "model_not_found"),
        ),
        (
            200,
            unhealthy("APIConnectionError: connection refused"),
            ProbeResult(False, "unreachable"),
        ),
        (200, unhealthy("something nobody planned for"), ProbeResult(False, "failed")),
        (500, "not even json-ish", ProbeResult(False, "failed")),
        (500, None, ProbeResult(False, "failed")),
    ],
)
def test_the_gateway_answer_becomes_a_stable_code(
    status: int, body: object, expected: ProbeResult
) -> None:
    assert classify_probe(status, body) == expected


def test_the_provider_text_and_the_key_are_never_in_the_result() -> None:
    result = classify_probe(200, unhealthy(LEAKY))
    assert "sk-live" not in repr(result) and "Incorrect" not in repr(result)


def gateway(handler: object, sessions: sessionmaker[Session]) -> LiteLLMGateway:
    client = httpx.Client(base_url="http://litellm:4000", transport=httpx.MockTransport(handler))  # type: ignore[arg-type]
    return LiteLLMGateway("http://litellm:4000", "master", sessions, client=client)


def test_the_probe_asks_the_gateway_for_that_model_only(sessions: sessionmaker[Session]) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=healthy())

    assert gateway(handler, sessions).probe("cheap") == ProbeResult(True, "ok")
    assert seen[0].url.path == "/health" and seen[0].url.params["model"] == "cheap"


def test_an_unreachable_gateway_is_a_code_not_an_exception(sessions: sessionmaker[Session]) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    assert gateway(handler, sessions).probe("cheap") == ProbeResult(False, "unreachable")


def test_a_reply_that_is_not_json_is_a_failure(sessions: sessionmaker[Session]) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="nope")

    assert gateway(handler, sessions).probe("cheap") == ProbeResult(False, "failed")


def test_a_probe_is_not_recorded_as_a_task_call(sessions: sessionmaker[Session]) -> None:
    from sqlalchemy import func, select

    from cobble.db import LLMCall

    gateway(lambda r: httpx.Response(200, json=healthy()), sessions).probe("cheap")
    with sessions() as db:
        assert db.scalar(select(func.count()).select_from(LLMCall)) == 0
