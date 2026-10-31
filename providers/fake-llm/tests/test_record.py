from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from fake_llm.app import create_app
from fake_llm.cassettes import CassetteStore
from fake_llm.record import Recorder

SECRET = "sk-abcdefghijklmnopqrstuvwx"
UPSTREAM_KEY = "upstream-key-should-never-be-stored"


def upstream(requests: list[httpx.Request], status: int = 200) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            status,
            json={
                "choices": [
                    {
                        "message": {"content": f"your key is {SECRET}"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 7, "completion_tokens": 5},
            },
        )

    return httpx.MockTransport(handler)


async def test_record_then_replay_without_secrets(tmp_path: Path) -> None:
    seen: list[httpx.Request] = []
    recorder = Recorder("http://up/v1", UPSTREAM_KEY, transport=upstream(seen))
    store = CassetteStore(tmp_path)
    app = create_app(store, mode="record", recorder=recorder)
    body = {"model": "m", "messages": [{"role": "user", "content": f"remember {SECRET}"}]}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://fake"
    ) as client:
        first = await client.post("/v1/chat/completions", json=body)
        second = await client.post("/v1/chat/completions", json=body)

    assert first.status_code == second.status_code == 200
    assert len(seen) == 1, "second identical request must be served from the cassette"
    assert seen[0].headers["authorization"] == f"Bearer {UPSTREAM_KEY}"

    files = list(tmp_path.glob("*.json"))
    assert len(files) == 1
    text = files[0].read_text("utf-8")
    assert SECRET not in text
    assert UPSTREAM_KEY not in text
    saved = json.loads(text)
    assert saved["response"]["prompt_tokens"] == 7

    # A fresh store (new process) replays the cassette for the original request.
    replay = create_app(CassetteStore(tmp_path))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=replay), base_url="http://fake"
    ) as client:
        again = await client.post("/v1/chat/completions", json=body)
    assert again.status_code == 200
    assert again.json()["usage"]["prompt_tokens"] == 7


async def test_upstream_error_is_502_and_leaks_nothing(tmp_path: Path) -> None:
    recorder = Recorder("http://up/v1", UPSTREAM_KEY, transport=upstream([], status=401))
    app = create_app(CassetteStore(tmp_path), mode="record", recorder=recorder)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://fake"
    ) as client:
        reply = await client.post(
            "/v1/chat/completions",
            json={"model": "m", "messages": [{"role": "user", "content": "x"}]},
        )
    assert reply.status_code == 502
    assert UPSTREAM_KEY not in reply.text
    assert list(tmp_path.glob("*.json")) == []


def test_record_mode_requires_recorder(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        create_app(CassetteStore(tmp_path), mode="record")
