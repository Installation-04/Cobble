"""Record mode: forward a request to a real provider and build a scrubbed cassette."""

from __future__ import annotations

from typing import Any

import httpx

from .cassettes import Cassette, Response, normalize_messages, request_key
from .scrub import scrub_text


class UpstreamError(RuntimeError):
    pass


class Recorder:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 120.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._transport = transport
        self._timeout = timeout

    async def record(self, body: dict[str, Any]) -> Cassette:
        model = str(body["model"])
        messages = normalize_messages(body["messages"])
        key = request_key(model, body["messages"])
        forwarded = {k: v for k, v in body.items() if k not in {"stream", "stream_options"}}
        async with httpx.AsyncClient(transport=self._transport, timeout=self._timeout) as client:
            reply = await client.post(
                f"{self._base_url}/chat/completions",
                json=forwarded,
                headers={"Authorization": f"Bearer {self._api_key}"},
            )
        if reply.status_code != 200:
            # Never include the upstream body or headers: they could echo secrets.
            raise UpstreamError(f"upstream returned HTTP {reply.status_code}")
        data = reply.json()
        choice = data["choices"][0]
        usage = data.get("usage") or {}
        return Cassette(
            key=key,
            model=model,
            messages=[{"role": m["role"], "content": scrub_text(m["content"])} for m in messages],
            response=Response(
                content=scrub_text(choice["message"].get("content") or ""),
                finish_reason=choice.get("finish_reason") or "stop",
                prompt_tokens=usage.get("prompt_tokens"),
                completion_tokens=usage.get("completion_tokens"),
            ),
        )
