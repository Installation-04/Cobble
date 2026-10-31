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


def test_activation_link_prints_url_and_expiry(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from sqlalchemy import create_engine
    from sqlalchemy.pool import StaticPool

    from cobble.db import ActivationToken, Base, make_session_factory

    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    sessions = make_session_factory(engine)
    monkeypatch.setattr(cli, "_session_factory", lambda _s: sessions)
    monkeypatch.setenv("COBBLE_PUBLIC_URL", "https://cobble.example/")
    monkeypatch.setenv("COBBLE_LANG", "en")

    assert cli.main(["activation-link"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[0].startswith("Activation link: https://cobble.example/activate?token=")
    assert "24 h" in lines[1]
    raw = lines[0].rsplit("token=", 1)[1]
    from cobble.auth.tokens import hash_token

    with sessions() as db:
        assert db.query(ActivationToken.token_hash).scalar() == hash_token(raw)


def test_activation_link_refuses_when_initialized(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from sqlalchemy import create_engine
    from sqlalchemy.pool import StaticPool

    from cobble.db import Base, User, make_session_factory

    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    sessions = make_session_factory(engine)
    with sessions() as db:
        db.add(User(email="a@b.co", password_hash="x"))
        db.commit()
    monkeypatch.setattr(cli, "_session_factory", lambda _s: sessions)
    monkeypatch.setenv("COBBLE_LANG", "fr")
    assert cli.main(["activation-link"]) == 1
    assert "déjà initialisé" in capsys.readouterr().err
