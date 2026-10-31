"""HTTP API: auth, validation, status codes and bodies."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest

from cobble_agent_service.app import create_app
from cobble_agent_service.config import ConfigError, Settings

from .conftest import RUN_TOKEN, TOKEN, Ctx, FakeEngine

AUTH = {"Authorization": f"Bearer {TOKEN}"}


def body(settings: Settings, **over: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "task_id": "T-001",
        "project_id": "p1",
        "repo_clone_url": f"{settings.forgejo_url}/proj.git",
        "base_branch": "main",
        "branch": "agent/t-001",
        "role": "worker",
        "model": "worker",
        "instructions": "x",
        "files": [],
        "test_command": "",
        "limits": {"max_iterations": 5, "max_seconds": 30, "cpu": 1, "memory_mb": 512, "pids": 64},
        "run_token": RUN_TOKEN,
        "marker": "[cobble-task:T-001:worker:1]",
    }
    data.update(over)
    return data


@pytest.fixture
async def client(settings: Settings) -> AsyncIterator[httpx.AsyncClient]:
    async def script(ctx: Ctx) -> int:
        ctx.emit("hello from the agent\n")
        ctx.commit()
        return 0

    app = create_app(settings, FakeEngine(script))
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t", headers=AUTH) as c:
            yield c


async def test_healthz_needs_no_token(client: httpx.AsyncClient) -> None:
    r = await client.get("/healthz", headers={"Authorization": ""})
    assert r.status_code == 200


@pytest.mark.parametrize(
    "headers",
    [
        {"Authorization": ""},
        {"Authorization": "Bearer wrong"},
        {"Authorization": "Basic abc"},
        {"Authorization": f"Bearer {TOKEN}x"},
    ],
)
async def test_every_endpoint_requires_the_bearer_token(
    client: httpx.AsyncClient, settings: Settings, headers: dict[str, str]
) -> None:
    calls = [
        client.post("/v1/runs", json=body(settings), headers=headers),
        client.get("/v1/runs/abc", headers=headers),
        client.get("/v1/runs/abc/logs", headers=headers),
        client.post("/v1/runs/abc/stop", headers=headers),
    ]
    for call in calls:
        r = await call
        assert r.status_code == 401
        assert r.json() == {"error": {"code": "unauthorized", "params": {}}}


async def test_token_is_compared_in_constant_time() -> None:
    import inspect

    from cobble_agent_service import app as module

    assert "hmac.compare_digest" in inspect.getsource(module)


async def test_full_flow(client: httpx.AsyncClient, settings: Settings) -> None:
    r = await client.post("/v1/runs", json=body(settings))
    assert r.status_code == 202
    run_id = r.json()["run_id"]
    for _ in range(200):
        status = (await client.get(f"/v1/runs/{run_id}")).json()
        if status["state"] != "running":
            break
        await asyncio.sleep(0.05)
    assert status["state"] == "done"
    assert set(status) >= {"state", "iterations", "exit_code", "head_sha", "log_tail"}
    assert status["exit_code"] == 0 and len(status["head_sha"]) == 40
    logs = await client.get(f"/v1/runs/{run_id}/logs", params={"offset": 0})
    assert logs.status_code == 200 and logs.headers["content-type"].startswith("text/plain")
    assert "hello from the agent" in logs.text
    nxt = int(logs.headers["X-Next-Offset"])
    assert nxt == len(logs.content)
    tail = await client.get(f"/v1/runs/{run_id}/logs", params={"offset": nxt})
    assert tail.content == b"" and tail.headers["X-Next-Offset"] == str(nxt)
    assert (await client.post(f"/v1/runs/{run_id}/stop")).status_code == 204


async def test_unknown_run_is_404(client: httpx.AsyncClient) -> None:
    for r in (await client.get("/v1/runs/nope"), await client.get("/v1/runs/nope/logs")):
        assert r.status_code == 404 and r.json()["error"]["code"] == "run_not_found"
    assert (await client.post("/v1/runs/nope/stop")).status_code == 404


@pytest.mark.parametrize(
    "over",
    [
        {"branch": "../evil"},
        {"branch": "a b"},
        {"branch": "x.lock"},
        {"task_id": "a/b"},
        {"files": ["../etc/passwd"]},
        {"files": ["/abs"]},
        {"model": "bad model"},
        {"marker": "two\nlines"},
        {"limits": {"max_seconds": 1}},
        {"limits": {"unknown": 1}},
        {"unknown_field": 1},
        {"run_token": "short"},
    ],
)
async def test_invalid_requests_are_422(
    client: httpx.AsyncClient, settings: Settings, over: dict[str, Any]
) -> None:
    r = await client.post("/v1/runs", json=body(settings, **over))
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "invalid_request"
    assert RUN_TOKEN not in r.text


async def test_foreign_repo_url_is_400(client: httpx.AsyncClient, settings: Settings) -> None:
    r = await client.post("/v1/runs", json=body(settings, repo_clone_url="http://evil/x.git"))
    assert r.status_code == 400 and r.json()["error"]["code"] == "repo_url_not_allowed"


def test_settings_require_the_secrets_and_one_data_location() -> None:
    with pytest.raises(ConfigError):
        Settings.from_env({})
    env = {
        "COBBLE_AGENT_SERVICE_TOKEN": "t",
        "COBBLE_AGENT_RUNNER_IMAGE": "img",
        "COBBLE_INTERNAL_API_URL": "http://api:8000/internal/llm/v1/",
        "COBBLE_PACK_FORGEJO_URL": "http://forgejo:3000",
        "COBBLE_PACK_FORGEJO_TOKEN": "ft",
    }
    with pytest.raises(ConfigError):
        Settings.from_env(env)  # neither volume nor host dir
    with pytest.raises(ConfigError):
        Settings.from_env(
            {**env, "COBBLE_AGENT_DATA_VOLUME": "v", "COBBLE_AGENT_DATA_HOST_DIR": "/h"}
        )
    ok = Settings.from_env({**env, "COBBLE_AGENT_DATA_VOLUME": "v"})
    assert ok.api_url == "http://api:8000/internal/llm/v1" and ok.network == "cobble_agents"
    assert "ft" not in repr(ok)
