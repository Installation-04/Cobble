"""The /demo proxy: prefix stripping, header hygiene, sandbox, wake-up and idle stop."""

from __future__ import annotations

import httpx
import pytest

from cobble_preview_service.app import create_app
from cobble_preview_service.config import Settings
from cobble_preview_service.manager import PreviewManager
from cobble_preview_service.models import PreviewRequest

from .conftest import PID, Clock, FakeEngine, Upstream, always_ready, payload

ID = f"{PID}-M1"
BASE = f"/demo/{PID}/M1"


async def deployed(client: httpx.AsyncClient, settings: Settings) -> PreviewManager:
    m: PreviewManager = client.app.state.manager  # type: ignore[attr-defined]
    await m.deploy(PreviewRequest.model_validate(payload(settings)))
    await m._tasks[ID]
    return m


async def test_prefix_is_stripped_and_the_body_streams_back(
    client: httpx.AsyncClient, settings: Settings, upstream: Upstream
) -> None:
    await deployed(client, settings)
    r = await client.get(f"{BASE}/api/todos?limit=3", headers={"Authorization": ""})
    assert r.status_code == 200 and r.text == "<html>hello demo</html>"
    sent = upstream.requests[-1]
    assert sent.url.host == f"cobble-preview-{ID.lower()}" and sent.url.port == 8000
    assert sent.url.path == "/api/todos" and sent.url.query == b"limit=3"
    assert sent.headers["x-forwarded-prefix"] == BASE
    assert (await client.get(f"{BASE}/")).status_code == 200
    assert upstream.requests[-1].url.path == "/"


async def test_cobble_credentials_never_reach_the_demo_and_cookies_never_leave(
    client: httpx.AsyncClient, settings: Settings, upstream: Upstream
) -> None:
    await deployed(client, settings)
    r = await client.get(
        f"{BASE}/",
        headers={
            "Authorization": "Bearer secret",
            "Cookie": "cobble_session=abc",
            "X-Requested-With": "cobble",
            "X-Other": "kept",
        },
    )
    sent = upstream.requests[-1].headers
    for name in ("authorization", "cookie", "x-requested-with"):
        assert name not in sent
    assert sent["x-other"] == "kept"
    assert "set-cookie" not in r.headers and r.headers["x-demo"] == "yes"


async def test_responses_are_sandboxed(
    client: httpx.AsyncClient, settings: Settings, upstream: Upstream
) -> None:
    await deployed(client, settings)
    upstream.headers = {"content-security-policy": "default-src *"}
    r = await client.get(f"{BASE}/")
    assert r.headers["content-security-policy"].startswith("sandbox allow-scripts")
    assert "allow-same-origin" not in r.headers["content-security-policy"]
    assert r.headers["access-control-allow-origin"] == "*"
    assert r.headers["x-content-type-options"] == "nosniff"
    pre = await client.options(
        f"{BASE}/api/x", headers={"Access-Control-Request-Headers": "content-type"}
    )
    assert pre.status_code == 204 and pre.headers["access-control-allow-headers"] == "content-type"
    assert len(upstream.requests) == 1  # the preflight is answered here


async def test_redirects_stay_under_the_prefix_and_post_bodies_pass(
    client: httpx.AsyncClient, settings: Settings, upstream: Upstream
) -> None:
    await deployed(client, settings)
    upstream.status = 302
    upstream.headers = {"location": "/login"}
    r = await client.post(f"{BASE}/api/todos", content=b'{"a":1}')
    assert r.status_code == 302 and r.headers["location"] == f"{BASE}/login"
    assert upstream.requests[-1].content == b'{"a":1}' and upstream.requests[-1].method == "POST"


async def test_missing_slash_redirects_and_unknown_demos_are_404(
    client: httpx.AsyncClient, settings: Settings
) -> None:
    r = await client.get(BASE)
    assert r.status_code == 308 and r.headers["location"] == f"{BASE}/"
    assert (await client.get(f"{BASE}/")).status_code == 404
    assert (await client.get("/demo/not-a-uuid/M1/")).status_code == 404
    assert (await client.get(f"/demo/{PID}/..%2fM1/")).status_code == 404


async def test_building_and_failed_demos_show_a_page(
    client: httpx.AsyncClient, settings: Settings
) -> None:
    m: PreviewManager = client.app.state.manager  # type: ignore[attr-defined]
    from cobble_preview_service.manager import Record

    m.records[ID] = Record(ID, PID, "M1", "milestone-M1", "file:///x", state="building")
    r = await client.get(f"{BASE}/")
    assert r.status_code == 503 and "refresh" in r.text and r.headers["retry-after"]
    m.records[ID].state = "failed"
    assert (await client.get(f"{BASE}/")).status_code == 502


async def test_unreachable_demo_is_a_bad_gateway(settings: Settings) -> None:

    def down(_r: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    app = create_app(
        settings, FakeEngine(), ready=always_ready, proxy_transport=httpx.MockTransport(down)
    )
    async with app.router.lifespan_context(app):
        m: PreviewManager = app.state.manager
        await m.deploy(PreviewRequest.model_validate(payload(settings)))
        await m._tasks[ID]
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://t"
        ) as c:
            assert (await c.get(f"{BASE}/")).status_code == 502


async def test_idle_previews_stop_and_wake_on_the_next_request(
    settings: Settings, engine: FakeEngine, upstream: Upstream
) -> None:
    clock = Clock()
    app = create_app(
        settings, engine, ready=always_ready, proxy_transport=httpx.MockTransport(upstream)
    )
    async with app.router.lifespan_context(app):
        m: PreviewManager = app.state.manager
        m._clock = clock
        await m.deploy(PreviewRequest.model_validate(payload(settings)))
        await m._tasks[ID]
        assert len(engine.live) == 1
        clock.now += 50
        assert await m.reap_once() == 0
        clock.now += 200
        assert await m.reap_once() == 1
        assert engine.live == [] and m.records[ID].state == "stopped"
        assert engine.images  # the image is kept
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://t"
        ) as c:
            status_calls = len(engine.builds)
            r = await c.get(f"{BASE}/")
            assert r.status_code == 200
            assert len(engine.builds) == status_calls  # woken from the image, not rebuilt
        assert len(engine.live) == 1 and m.records[ID].state == "running"


async def test_traffic_keeps_a_preview_alive(
    settings: Settings, engine: FakeEngine, upstream: Upstream
) -> None:
    clock = Clock()
    app = create_app(
        settings, engine, ready=always_ready, proxy_transport=httpx.MockTransport(upstream)
    )
    async with app.router.lifespan_context(app):
        m: PreviewManager = app.state.manager
        m._clock = clock
        await m.deploy(PreviewRequest.model_validate(payload(settings)))
        await m._tasks[ID]
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://t"
        ) as c:
            for _ in range(5):
                clock.now += 60
                assert (await c.get(f"{BASE}/")).status_code == 200
                assert await m.reap_once() == 0


async def test_oldest_idle_preview_is_stopped_to_stay_within_max_running(
    settings: Settings, engine: FakeEngine, upstream: Upstream
) -> None:
    clock = Clock()
    app = create_app(
        settings, engine, ready=always_ready, proxy_transport=httpx.MockTransport(upstream)
    )
    async with app.router.lifespan_context(app):
        m: PreviewManager = app.state.manager
        m._clock = clock
        for ms in ("M1", "M2", "M3"):
            clock.now += 1
            req = PreviewRequest.model_validate(payload(settings, milestone=ms))
            await m.deploy(req)
            await m._tasks[req.id]
        states = {r.milestone: r.state for r in m.records.values()}
        assert states == {"M1": "stopped", "M2": "running", "M3": "running"}


@pytest.mark.parametrize("sandbox", [False])
async def test_sandbox_can_be_switched_off(
    settings: Settings, engine: FakeEngine, upstream: Upstream, sandbox: bool
) -> None:
    from dataclasses import replace

    app = create_app(
        replace(settings, sandbox=sandbox),
        engine,
        ready=always_ready,
        proxy_transport=httpx.MockTransport(upstream),
    )
    async with app.router.lifespan_context(app):
        m: PreviewManager = app.state.manager
        await m.deploy(PreviewRequest.model_validate(payload(settings)))
        await m._tasks[ID]
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://t"
        ) as c:
            r = await c.get(f"{BASE}/")
            assert "content-security-policy" not in r.headers
