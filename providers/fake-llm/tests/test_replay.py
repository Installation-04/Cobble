from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from fake_llm.app import create_app
from fake_llm.cassettes import CassetteStore

from .conftest import REPO_CASSETTES

HI = {"model": "m", "messages": [{"role": "user", "content": "hi"}]}


async def test_replays_matching_cassette(client: httpx.AsyncClient) -> None:
    reply = await client.post("/v1/chat/completions", json=HI)
    assert reply.status_code == 200
    data = reply.json()
    assert data["choices"][0]["message"]["content"] == "hello there friend"
    assert data["usage"] == {"prompt_tokens": 1, "completion_tokens": 3, "total_tokens": 4}


async def test_unknown_request_is_404_in_strict_mode(client: httpx.AsyncClient) -> None:
    reply = await client.post(
        "/v1/chat/completions",
        json={"model": "m", "messages": [{"role": "user", "content": "other"}]},
    )
    assert reply.status_code == 404
    error = reply.json()["error"]
    assert error["type"] == "cassette_not_found"
    assert len(error["code"]) == 64


async def test_default_cassette_when_allowed(cassette_dir: Path) -> None:
    app = create_app(CassetteStore(cassette_dir), allow_default=True)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://fake") as c:
        reply = await c.post(
            "/v1/chat/completions",
            json={"model": "m", "messages": [{"role": "user", "content": "anything"}]},
        )
    assert reply.json()["choices"][0]["message"]["content"] == "default reply here"


async def test_streaming_matches_non_streaming(client: httpx.AsyncClient) -> None:
    reply = await client.post(
        "/v1/chat/completions",
        json={**HI, "stream": True, "stream_options": {"include_usage": True}},
    )
    assert reply.headers["content-type"].startswith("text/event-stream")
    lines = [ln[6:] for ln in reply.text.splitlines() if ln.startswith("data: ")]
    assert lines[-1] == "[DONE]"
    chunks = [json.loads(ln) for ln in lines[:-1]]
    text = "".join(c["choices"][0]["delta"].get("content", "") for c in chunks if c["choices"])
    assert text == "hello there friend"
    assert chunks[-1]["usage"]["completion_tokens"] == 3


async def test_invalid_request_is_400(client: httpx.AsyncClient) -> None:
    reply = await client.post("/v1/chat/completions", json={"model": "m"})
    assert reply.status_code == 400


async def test_models_and_health(client: httpx.AsyncClient) -> None:
    assert (await client.get("/healthz")).json()["status"] == "ok"
    ids = [m["id"] for m in (await client.get("/v1/models")).json()["data"]]
    assert ids == ["fake", "m"]


async def test_repository_cassettes_are_valid_and_hello_matches() -> None:
    store = CassetteStore(REPO_CASSETTES)
    assert store.default is not None
    app = create_app(store)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://fake") as c:
        reply = await c.post(
            "/v1/chat/completions",
            json={"model": "fake", "messages": [{"role": "user", "content": "hello"}]},
        )
    assert reply.status_code == 200
    assert "Cobble fake LLM" in reply.json()["choices"][0]["message"]["content"]


async def test_marker_cassette_matches_whatever_the_rest_of_the_prompt_says(tmp_path: Path) -> None:
    (tmp_path / "t1.json").write_text(
        json.dumps(
            {
                "version": 1,
                "match": {"marker": "[cobble-task:T-001:worker:1]"},
                "response": {"content": "file.py\n```python\nprint(1)\n```"},
            }
        )
    )
    app = create_app(CassetteStore(tmp_path))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://f") as c:
        body = {
            "model": "whatever",
            "messages": [
                {"role": "system", "content": "repo map: lots of text that changes"},
                {"role": "user", "content": "Do the task. [cobble-task:T-001:worker:1] Thanks."},
            ],
        }
        hit = await c.post("/v1/chat/completions", json=body)
        other = {**body, "messages": [{"role": "user", "content": "[cobble-task:T-002:worker:1]"}]}
        miss = await c.post("/v1/chat/completions", json=other)
    assert hit.status_code == 200
    assert "print(1)" in hit.json()["choices"][0]["message"]["content"]
    assert miss.status_code == 404


def test_invalid_marker_is_rejected(tmp_path: Path) -> None:
    (tmp_path / "bad.json").write_text(
        json.dumps({"version": 1, "match": {"marker": "T-001"}, "response": {"content": "x"}})
    )
    with pytest.raises(ValueError):
        CassetteStore(tmp_path)
