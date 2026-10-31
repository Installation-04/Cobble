"""Management API: auth, validation, deploy/status/delete, failures, restarts."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest

from cobble_preview_service.app import create_app
from cobble_preview_service.config import ConfigError, Settings
from cobble_preview_service.manager import PreviewManager

from .conftest import (
    FORGEJO_SECRET,
    PID,
    FakeEngine,
    Upstream,
    always_ready,
    clone_url,
    payload,
)

ID = f"{PID}-M1"


def manager(client: httpx.AsyncClient) -> PreviewManager:
    m: PreviewManager = client.app.state.manager  # type: ignore[attr-defined]
    return m


async def settled(client: httpx.AsyncClient, state: str = "running", limit: float = 10) -> Any:
    for _ in range(int(limit / 0.02)):
        data = (await client.get(f"/v1/previews/{ID}")).json()
        if data["state"] == state:
            return data
        await asyncio.sleep(0.02)
    raise AssertionError(f"still {data['state']}: {data}")


async def test_healthz_needs_no_token(client: httpx.AsyncClient) -> None:
    assert (await client.get("/healthz", headers={"Authorization": ""})).status_code == 200


@pytest.mark.parametrize("headers", [{"Authorization": ""}, {"Authorization": "Bearer nope"}])
async def test_v1_requires_the_token(client: httpx.AsyncClient, headers: dict[str, str]) -> None:
    for method, path in (("GET", f"/v1/previews/{ID}"), ("DELETE", f"/v1/previews/{ID}")):
        assert (await client.request(method, path, headers=headers)).status_code == 401
    assert (await client.post("/v1/previews", json={}, headers=headers)).status_code == 401


@pytest.mark.parametrize(
    "over",
    [
        {"milestone": "M1; rm"},
        {"ref": "--upload-pack=x"},
        {"ref": "a..b"},
        {"project_id": "nope"},
        {"repo_clone_url": "ssh://x/y.git"},
        {"extra": 1},
    ],
)
async def test_invalid_requests_are_422(
    client: httpx.AsyncClient, settings: Settings, over: dict[str, Any]
) -> None:
    r = await client.post("/v1/previews", json=payload(settings, **over))
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "validation_error"


async def test_deploy_builds_runs_and_reports(
    client: httpx.AsyncClient, settings: Settings, engine: FakeEngine
) -> None:
    r = await client.post("/v1/previews", json=payload(settings))
    assert r.status_code == 202
    assert r.json()["path"] == f"/demo/{PID}/M1/"
    assert r.json()["state"] == "building"
    data = await settled(client)
    assert data["ref"] == "milestone-M1" and data["idle"] is False
    (build,) = engine.builds
    assert "Dockerfile" in build["names"] and "app.txt" in build["names"]
    assert not any(n.startswith(".git") for n in build["names"])  # no .git, so no credentials
    assert build["labels"]["cobble.preview.id"] == ID
    assert len(engine.live) == 1


async def test_container_is_confined(
    client: httpx.AsyncClient, settings: Settings, engine: FakeEngine
) -> None:
    await client.post("/v1/previews", json=payload(settings))
    await settled(client)
    (container,) = engine.live
    body = container["body"]
    host = body["HostConfig"]
    assert body["User"] == "10001:10001"
    assert host["ReadonlyRootfs"] is True and host["CapDrop"] == ["ALL"]
    assert "no-new-privileges:true" in host["SecurityOpt"] and host["Privileged"] is False
    assert host["Memory"] == 512 * 1024 * 1024 and host["PidsLimit"] == 256
    assert host["NanoCpus"] == 1_000_000_000
    assert host["NetworkMode"] == "cobble_previews"
    assert "PortBindings" not in host and "Binds" not in host and "Mounts" not in host
    assert "ExposedPorts" not in body
    assert not any("TOKEN" in e or "SECRET" in e for e in body["Env"])
    assert container["name"] == f"cobble-preview-{ID.lower()}"


async def test_same_ref_is_idempotent_and_a_new_ref_replaces(
    client: httpx.AsyncClient, settings: Settings, engine: FakeEngine
) -> None:
    await client.post("/v1/previews", json=payload(settings))
    await settled(client)
    again = await client.post("/v1/previews", json=payload(settings))
    assert again.status_code == 202 and again.json()["state"] == "running"
    assert len(engine.builds) == 1
    await client.post("/v1/previews", json=payload(settings, ref="milestone-M1-r2"))
    for _ in range(300):
        data = (await client.get(f"/v1/previews/{ID}")).json()
        if data["ref"] == "milestone-M1-r2" and data["state"] == "running":
            break
        await asyncio.sleep(0.02)
    assert len(engine.builds) == 2 and len(engine.live) == 1
    assert engine.removed_images == ["cobble-preview/" + ID.lower() + ":milestone-m1"]


async def test_delete_removes_container_and_image(
    client: httpx.AsyncClient, settings: Settings, engine: FakeEngine
) -> None:
    await client.post("/v1/previews", json=payload(settings))
    await settled(client)
    assert (await client.delete(f"/v1/previews/{ID}")).status_code == 204
    assert (await client.get(f"/v1/previews/{ID}")).status_code == 404
    assert engine.live == [] and engine.images == set()
    assert (await client.delete(f"/v1/previews/{ID}")).status_code == 204  # idempotent


async def test_build_failure_is_reported_without_secrets(
    client: httpx.AsyncClient, settings: Settings, engine: FakeEngine
) -> None:
    engine.build_error = f"step 3 failed {FORGEJO_SECRET}"
    await client.post("/v1/previews", json=payload(settings))
    data = await settled(client, "failed")
    assert "step 3 failed" in data["detail"] and FORGEJO_SECRET not in data["detail"]
    engine.build_error = ""
    again = await client.post("/v1/previews", json=payload(settings))  # a failed one is retried
    assert again.json()["state"] == "building"
    await settled(client)


@pytest.mark.parametrize(
    ("over", "detail"),
    [
        ({"ref": "milestone-M2"}, "no_dockerfile"),
        ({"ref": "milestone-ghost"}, "git_failed"),
        ({"repo_clone_url": "https://evil.example/x.git"}, "repo_url_not_allowed"),
    ],
)
async def test_source_problems_fail_the_preview(
    client: httpx.AsyncClient, settings: Settings, over: dict[str, Any], detail: str
) -> None:
    await client.post("/v1/previews", json=payload(settings, **over))
    data = await settled(client, "failed")
    assert detail in data["detail"]


async def test_container_that_exits_at_start_fails(
    client: httpx.AsyncClient, settings: Settings, engine: FakeEngine
) -> None:
    async def never(_url: str) -> bool:
        return False

    manager(client)._ready = never
    engine.exit_at_start = True
    await client.post("/v1/previews", json=payload(settings))
    data = await settled(client, "failed")
    assert "exited" in data["detail"]


async def test_state_survives_a_restart_and_unfinished_builds_resume(
    settings: Settings, engine: FakeEngine
) -> None:
    app = create_app(
        settings, engine, ready=always_ready, proxy_transport=httpx.MockTransport(Upstream())
    )
    async with app.router.lifespan_context(app):
        m: PreviewManager = app.state.manager
        from cobble_preview_service.models import PreviewRequest

        await m.deploy(PreviewRequest.model_validate(payload(settings)))
        for _ in range(500):
            if m.records[ID].state == "running":
                break
            await asyncio.sleep(0.02)
        assert m.records[ID].state == "running"
        m.records[ID + "x"] = m.records[ID].__class__(
            id=f"{PID}-M2",
            project_id=PID,
            milestone="M2",
            ref="milestone-M1",
            repo_clone_url=clone_url(settings),
            state="building",
        )
        m.records[f"{PID}-M2"] = m.records.pop(ID + "x")
        m._save()
    engine.running.clear()  # the daemon restarted too: nothing runs
    app2 = create_app(
        settings, engine, ready=always_ready, proxy_transport=httpx.MockTransport(Upstream())
    )
    async with app2.router.lifespan_context(app2):
        m2: PreviewManager = app2.state.manager
        assert m2.records[ID].state == "stopped"  # woken on demand
        for _ in range(500):
            if m2.records[f"{PID}-M2"].state == "running":
                break
            await asyncio.sleep(0.02)
        assert m2.records[f"{PID}-M2"].state == "running"


def test_settings_from_env() -> None:
    env = {
        "COBBLE_PREVIEW_SERVICE_TOKEN": "t",
        "COBBLE_PACK_FORGEJO_URL": "http://forgejo:3000/",
        "COBBLE_PACK_FORGEJO_TOKEN": "f",
        "COBBLE_PREVIEW_BUILD_ARGS": '{"A": "b"}',
        "COBBLE_PREVIEW_SANDBOX": "0",
    }
    s = Settings.from_env(env)
    assert s.forgejo_url == "http://forgejo:3000" and s.build_args == {"A": "b"}
    assert s.sandbox is False and s.network == "cobble_previews" and s.memory_mb == 512
    with pytest.raises(ConfigError):
        Settings.from_env({})
    with pytest.raises(ConfigError):
        Settings.from_env({**env, "COBBLE_PREVIEW_BUILD_ARGS": "[1]"})
