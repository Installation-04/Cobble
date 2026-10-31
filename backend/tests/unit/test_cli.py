from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from cobble import cli
from cobble.router.gateway import ChatResult, GatewayError


class FakeGateway:
    error: GatewayError | None = None

    def __init__(self, *_a: Any, **_kw: Any) -> None:
        pass

    def chat(self, model: str, messages: list[dict[str, Any]], **_kw: Any) -> ChatResult:
        if self.error:
            raise self.error
        return ChatResult("hello back", model, 4, 6, Decimal("0.001"), "r1")


@pytest.fixture(autouse=True)
def _patch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "LiteLLMGateway", FakeGateway)
    monkeypatch.setattr(cli, "Redis", type("R", (), {"from_url": staticmethod(lambda _u: None)}))
    uncached = cli.get_settings.__wrapped__
    monkeypatch.setattr(cli, "get_settings", uncached)


def test_chat_prints_reply_tokens_and_cost(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("COBBLE_LANG", "fr")
    assert cli.main(["chat", "hello"]) == 0
    out = capsys.readouterr().out
    assert "Réponse: hello back" in out
    assert "4 / 6" in out
    assert "0.001" in out


def test_chat_gateway_error_exits_1(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("COBBLE_LANG", "en")
    monkeypatch.setattr(FakeGateway, "error", GatewayError(502))
    assert cli.main(["chat", "hello"]) == 1
    assert "502" in capsys.readouterr().err
