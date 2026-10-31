from __future__ import annotations

import json
import uuid
from typing import Any

import httpx
import pytest

from cobble.capabilities.agent import (
    AgentLimits,
    AgentOutcome,
    AgentRejected,
    AgentRunNotFound,
    AgentTask,
    AgentUnavailable,
)
from cobble.capabilities.llm import Role
from cobble.config import Settings
from cobble.providers.agent_service import HttpAgentRunner, build_pack_services

TOKEN = "agent-service-secret"
TASK = AgentTask(
    task_id=uuid.UUID(int=1),
    project_id=uuid.UUID(int=2),
    repo_clone_url="http://git/x.git",
    branch="task/t-001",
    role=Role.WORKER,
    instructions="[cobble-task:T-001:worker:1]\ndo it",
    files=["app/a.py"],
    limits=AgentLimits(max_iterations=7, max_seconds=60, cpu=0.5, memory_mb=512, pids=64),
    model="cheap",
    base_branch="main",
    test_command="uv run pytest -q tests/a.py",
    run_token="signed.token",
    marker="[cobble-task:T-001:worker:1]",
)


def runner(handler: Any) -> HttpAgentRunner:
    return HttpAgentRunner(
        "http://agents:8080/", TOKEN, transport=httpx.MockTransport(handler), sleep=lambda _s: None
    )


def test_start_posts_the_documented_body_with_the_bearer_token() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(202, json={"run_id": "r-1"})

    assert runner(handler).start(TASK) == "r-1"
    (request,) = seen
    assert (request.method, request.url.path) == ("POST", "/v1/runs")
    assert request.headers["authorization"] == f"Bearer {TOKEN}"
    assert json.loads(request.content) == {
        "task_id": str(uuid.UUID(int=1)),
        "project_id": str(uuid.UUID(int=2)),
        "repo_clone_url": "http://git/x.git",
        "base_branch": "main",
        "branch": "task/t-001",
        "role": "worker",
        "model": "cheap",
        "instructions": "[cobble-task:T-001:worker:1]\ndo it",
        "files": ["app/a.py"],
        "test_command": "uv run pytest -q tests/a.py",
        "limits": {
            "max_iterations": 7,
            "max_seconds": 60,
            "cpu": 0.5,
            "memory_mb": 512,
            "pids": 64,
        },
        "run_token": "signed.token",
        "marker": "[cobble-task:T-001:worker:1]",
    }


@pytest.mark.parametrize(
    ("state", "outcome"),
    [
        ("done", AgentOutcome.DONE),
        ("failed", AgentOutcome.FAILED),
        ("timeout", AgentOutcome.TIMEOUT),
        ("loop_detected", AgentOutcome.LOOP_DETECTED),
        ("stopped", AgentOutcome.STOPPED),
    ],
)
def test_poll_maps_final_states(state: str, outcome: AgentOutcome) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert (request.method, request.url.path) == ("GET", "/v1/runs/r-1")
        assert request.headers["authorization"] == f"Bearer {TOKEN}"
        return httpx.Response(
            200,
            json={
                "state": state,
                "iterations": 5,
                "exit_code": 1,
                "head_sha": "abc123",
                "log_tail": "last lines",
            },
        )

    result = runner(handler).poll("r-1")
    assert result is not None
    assert result.outcome is outcome
    assert (result.iterations, result.exit_code, result.head_sha) == (5, 1, "abc123")
    assert result.log == "last lines"


def test_poll_returns_none_while_running_and_tolerates_missing_fields() -> None:
    assert runner(lambda _r: httpx.Response(200, json={"state": "running"})).poll("r") is None
    result = runner(lambda _r: httpx.Response(200, json={"state": "done"})).poll("r")
    assert result is not None
    assert (result.iterations, result.exit_code, result.head_sha, result.log) == (0, None, None, "")


def test_unknown_state_is_a_failure_not_a_crash() -> None:
    result = runner(lambda _r: httpx.Response(200, json={"state": "weird"})).poll("r")
    assert result is not None
    assert result.outcome is AgentOutcome.FAILED
    assert "weird" in result.log


def test_unknown_run_is_reported() -> None:
    with pytest.raises(AgentRunNotFound):
        runner(lambda _r: httpx.Response(404)).poll("gone")


def test_stop_posts_and_ignores_a_run_that_is_already_gone() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(204 if len(seen) == 1 else 404)

    client = runner(handler)
    client.stop("r-1")
    client.stop("r-2")
    assert [(r.method, r.url.path) for r in seen] == [
        ("POST", "/v1/runs/r-1/stop"),
        ("POST", "/v1/runs/r-2/stop"),
    ]
    with pytest.raises(AgentUnavailable):
        runner(lambda _r: httpx.Response(500)).stop("r")


def test_unreachable_service_is_unavailable_not_a_task_failure() -> None:
    def down(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused to http://agents:8080")

    client = runner(down)
    with pytest.raises(AgentUnavailable) as start_error:
        client.start(TASK)
    with pytest.raises(AgentUnavailable):
        client.poll("r")
    with pytest.raises(AgentUnavailable):
        client.stop("r")
    assert TOKEN not in str(start_error.value)


@pytest.mark.parametrize("status", [500, 502, 503, 429])
def test_server_errors_are_retryable(status: int) -> None:
    client = runner(lambda _r: httpx.Response(status))
    with pytest.raises(AgentUnavailable):
        client.start(TASK)
    with pytest.raises(AgentUnavailable):
        client.poll("r")


@pytest.mark.parametrize("status", [400, 401, 403, 409, 422])
def test_refused_start_is_rejected(status: int) -> None:
    with pytest.raises(AgentRejected):
        runner(lambda _r: httpx.Response(status, json={"error": "nope"})).start(TASK)


def test_unreadable_answers_are_retryable() -> None:
    with pytest.raises(AgentUnavailable):
        runner(lambda _r: httpx.Response(202, text="not json")).start(TASK)
    with pytest.raises(AgentUnavailable):
        runner(lambda _r: httpx.Response(200, text="<html>")).poll("r")


def test_run_blocks_until_the_service_reports_a_result() -> None:
    answers = [
        httpx.Response(202, json={"run_id": "r-9"}),
        httpx.Response(200, json={"state": "running"}),
        httpx.Response(200, json={"state": "running"}),
        httpx.Response(200, json={"state": "done", "iterations": 3}),
    ]
    result = runner(lambda _r: answers.pop(0)).run(TASK)
    assert result.outcome is AgentOutcome.DONE
    assert result.iterations == 3
    assert answers == []


def test_from_settings_uses_url_and_token() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(202, json={"run_id": "r"})

    client = HttpAgentRunner.from_settings(
        Settings(agent_service_url="http://svc:9/", agent_service_token="tok")
    )
    client._client = httpx.Client(  # swap the transport, keep the configured headers/base URL
        base_url=client._client.base_url,
        headers=client._client.headers,
        transport=httpx.MockTransport(handler),
    )
    assert client.start(TASK) == "r"
    assert str(seen[0].url) == "http://svc:9/v1/runs"
    assert seen[0].headers["authorization"] == "Bearer tok"


def test_pack_services_are_not_built_without_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("COBBLE_PACK_FORGEJO_TOKEN", "COBBLE_PACK_WOODPECKER_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    assert build_pack_services(Settings(agent_service_token="t")) is None
    monkeypatch.setenv("COBBLE_PACK_FORGEJO_TOKEN", "a")
    monkeypatch.setenv("COBBLE_PACK_WOODPECKER_TOKEN", "b")
    assert build_pack_services(Settings(agent_service_token="")) is None
    services = build_pack_services(Settings(agent_service_token="t"))
    assert services is not None
    assert isinstance(services.agents, HttpAgentRunner)
