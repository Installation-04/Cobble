"""Cassette format, request keys and on-disk store."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CASSETTE_VERSION = 1
Message = dict[str, Any]


def normalize_messages(messages: list[Message]) -> list[dict[str, str]]:
    """Keep only role and text content so keys do not depend on client details."""
    out: list[dict[str, str]] = []
    for message in messages:
        content = message.get("content") or ""
        if isinstance(content, list):
            content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
        out.append({"role": str(message.get("role", "")), "content": str(content)})
    return out


def request_key(model: str, messages: list[Message]) -> str:
    canonical = json.dumps(
        {"model": model, "messages": normalize_messages(messages)},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Response:
    content: str
    finish_reason: str = "stop"
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


@dataclass(frozen=True)
class Cassette:
    key: str | None
    response: Response
    model: str | None = None
    messages: list[dict[str, str]] | None = None
    is_default: bool = False

    def to_json(self) -> dict[str, Any]:
        response: dict[str, Any] = {
            "content": self.response.content,
            "finish_reason": self.response.finish_reason,
        }
        if self.response.prompt_tokens is not None:
            response["prompt_tokens"] = self.response.prompt_tokens
        if self.response.completion_tokens is not None:
            response["completion_tokens"] = self.response.completion_tokens
        data: dict[str, Any] = {"version": CASSETTE_VERSION}
        if self.is_default:
            data["default"] = True
        else:
            data["request"] = {"key": self.key, "model": self.model, "messages": self.messages}
        data["response"] = response
        return data

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> Cassette:
        if data.get("version") != CASSETTE_VERSION:
            raise ValueError(f"unsupported cassette version: {data.get('version')!r}")
        raw = data["response"]
        response = Response(
            content=raw["content"],
            finish_reason=raw.get("finish_reason", "stop"),
            prompt_tokens=raw.get("prompt_tokens"),
            completion_tokens=raw.get("completion_tokens"),
        )
        if data.get("default"):
            return cls(key=None, response=response, is_default=True)
        request = data["request"]
        model = request["model"]
        messages = normalize_messages(request["messages"])
        # A recorded cassette stores the key of the original request: its messages
        # may have been scrubbed, so the key cannot be recomputed from them.
        return cls(
            key=request.get("key") or request_key(model, messages),
            response=response,
            model=model,
            messages=messages,
        )


class CassetteStore:
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self._by_key: dict[str, Cassette] = {}
        self._default: Cassette | None = None
        self.load()

    def load(self) -> None:
        self._by_key.clear()
        self._default = None
        for path in sorted(self.directory.glob("*.json")):
            cassette = Cassette.from_json(json.loads(path.read_text("utf-8")))
            if cassette.is_default:
                self._default = cassette
            elif cassette.key is not None:
                self._by_key[cassette.key] = cassette

    @property
    def default(self) -> Cassette | None:
        return self._default

    def models(self) -> list[str]:
        return sorted({c.model for c in self._by_key.values() if c.model})

    def get(self, key: str) -> Cassette | None:
        return self._by_key.get(key)

    def write(self, cassette: Cassette) -> Path:
        if cassette.key is None:
            raise ValueError("cannot write a default cassette")
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.directory / f"{cassette.key[:16]}.json"
        path.write_text(
            json.dumps(cassette.to_json(), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        self._by_key[cassette.key] = cassette
        return path
