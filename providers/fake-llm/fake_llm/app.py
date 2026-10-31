"""OpenAI-compatible HTTP API that replays cassettes."""

from __future__ import annotations

import json
import os
import time
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from .cassettes import Cassette, CassetteStore, normalize_messages, request_key
from .record import Recorder, UpstreamError

Mode = Literal["replay", "record"]
DEFAULT_MODEL = "fake"


def count_tokens(text: str) -> int:
    """Deterministic fake tokenizer: one token per whitespace-separated word."""
    return len(text.split())


def _usage(cassette: Cassette, body: dict[str, Any]) -> dict[str, int]:
    prompt = cassette.response.prompt_tokens
    if prompt is None:
        prompt = sum(count_tokens(m["content"]) for m in normalize_messages(body["messages"]))
    completion = cassette.response.completion_tokens
    if completion is None:
        completion = count_tokens(cassette.response.content)
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": prompt + completion,
    }


def _completion(cassette: Cassette, body: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:24]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": body.get("model", DEFAULT_MODEL),
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": cassette.response.content},
                "finish_reason": cassette.response.finish_reason,
            }
        ],
        "usage": _usage(cassette, body),
    }


def _sse(data: dict[str, Any] | str) -> str:
    payload = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)
    return f"data: {payload}\n\n"


async def _stream(cassette: Cassette, body: dict[str, Any]) -> AsyncIterator[str]:
    base = {
        "id": f"chatcmpl-{uuid.uuid4().hex[:24]}",
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": body.get("model", DEFAULT_MODEL),
    }

    def chunk(delta: dict[str, Any], finish: str | None = None) -> dict[str, Any]:
        return {**base, "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}

    yield _sse(chunk({"role": "assistant", "content": ""}))
    pieces = cassette.response.content.split(" ")
    for index, piece in enumerate(pieces):
        yield _sse(chunk({"content": piece if index == 0 else f" {piece}"}))
    yield _sse(chunk({}, cassette.response.finish_reason))
    options = body.get("stream_options") or {}
    if options.get("include_usage"):
        yield _sse({**base, "choices": [], "usage": _usage(cassette, body)})
    yield _sse("[DONE]")


def _error(status: int, message: str, kind: str, code: str | None = None) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"message": message, "type": kind, "code": code}},
    )


def create_app(
    store: CassetteStore,
    *,
    mode: Mode = "replay",
    allow_default: bool = False,
    recorder: Recorder | None = None,
) -> FastAPI:
    if mode == "record" and recorder is None:
        raise ValueError("record mode needs a recorder")
    app = FastAPI(title="Cobble fake LLM", docs_url=None, redoc_url=None)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok", "mode": mode}

    @app.get("/v1/models")
    async def models() -> dict[str, Any]:
        names = sorted({DEFAULT_MODEL, *store.models()})
        return {
            "object": "list",
            "data": [{"id": n, "object": "model", "owned_by": "cobble-fake-llm"} for n in names],
        }

    @app.post("/v1/chat/completions", response_model=None)
    async def chat(request: Request) -> Response:
        try:
            body = await request.json()
            model = str(body["model"])
            messages = body["messages"]
            if not isinstance(messages, list):
                raise TypeError("messages must be a list")
        except (ValueError, KeyError, TypeError):
            return _error(400, "invalid chat completion request", "invalid_request_error")

        key = request_key(model, messages)
        cassette = store.get(key) or store.find_marker(messages)
        if cassette is None and recorder is not None:
            try:
                cassette = await recorder.record(body)
            except UpstreamError as exc:
                return _error(502, str(exc), "upstream_error")
            store.write(cassette)
        if cassette is None and allow_default:
            cassette = store.default
        if cassette is None:
            return _error(
                404,
                f"No cassette for request key {key}. "
                "Record one with `make cassettes` or add a default cassette.",
                "cassette_not_found",
                key,
            )

        if body.get("stream"):
            return StreamingResponse(_stream(cassette, body), media_type="text/event-stream")
        return JSONResponse(_completion(cassette, body))

    return app


def create_app_from_env() -> FastAPI:
    """Entry point for uvicorn (`--factory`). Configuration comes from the environment."""
    store = CassetteStore(Path(os.environ.get("FAKE_LLM_CASSETTES", "cassettes")))
    mode: Mode = "record" if os.environ.get("FAKE_LLM_MODE") == "record" else "replay"
    recorder = None
    if mode == "record":
        recorder = Recorder(
            base_url=os.environ["FAKE_LLM_UPSTREAM_URL"],
            api_key=os.environ["FAKE_LLM_UPSTREAM_API_KEY"],
        )
    return create_app(
        store,
        mode=mode,
        allow_default=os.environ.get("FAKE_LLM_ALLOW_DEFAULT") == "1",
        recorder=recorder,
    )
