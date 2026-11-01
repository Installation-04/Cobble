"""Model connections: API keys encrypted at rest, given to the gateway, never shown."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

import pytest
import yaml
from sqlalchemy import select

from cobble.db.models import LlmConnection, PlatformState
from cobble.module_manager.connections import (
    PROVIDERS,
    ConnectionInvalid,
    ConnectionStore,
    ConnectionUnknown,
    validate,
)
from cobble.module_manager.llm import LlmEntry, render_models
from cobble.module_manager.manager import ManagerBusy
from cobble.module_manager.redaction import Redactor
from cobble.module_manager.runner import RunnerError
from cobble.module_manager.vault import SecretValue, Vault, VaultError

from .test_module_manager import MASTER, OLLAMA, Rig

KEY = "sk-test-0123456789abcdef"


def store() -> ConnectionStore:
    return ConnectionStore(Vault({1: MASTER}), Redactor())


class Gateway:
    def __init__(self) -> None:
        self.calls: list[list[LlmEntry]] = []
        self.fail = False

    def sync(self, entries: Sequence[LlmEntry]) -> None:
        if self.fail:
            raise RunnerError("llm_failed")
        self.calls.append(list(entries))

    @property
    def last(self) -> list[LlmEntry]:
        return self.calls[-1]


def rig(**kw: Any) -> tuple[Rig, Gateway]:
    gateway = Gateway()
    return Rig(modules=[OLLAMA], llm=gateway, connections=store(), **kw), gateway


def put(r: Rig, name: str = "cheap", **kw: Any) -> None:
    args: dict[str, Any] = {"provider": "openai", "model": "gpt-4.1-mini", "api_key": KEY}
    args.update(kw)
    r.manager.put_model(
        name,
        args["provider"],
        args["model"],
        SecretValue(args["api_key"]),
        args.get("base_url"),
        make_default=args.get("make_default", False),
    )


# --- validation ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("label", "args", "bad"),
    [
        ("ok", ("cheap", "openai", "gpt-4.1-mini", KEY, None), []),
        ("reserved name", ("fake", "openai", "gpt", KEY, None), ["name"]),
        ("reserved default", ("default", "openai", "gpt", KEY, None), ["name"]),
        ("upper case name", ("Cheap", "openai", "gpt", KEY, None), ["name"]),
        ("name with a slash", ("a/b", "openai", "gpt", KEY, None), ["name"]),
        ("unknown provider", ("x", "skynet", "gpt", KEY, None), ["provider"]),
        ("hostile model", ("x", "openai", "gpt; rm -rf /", KEY, None), ["model"]),
        ("empty key", ("x", "openai", "gpt", "   ", None), ["api_key"]),
        ("key with a space", ("x", "openai", "gpt", "sk abc", None), ["api_key"]),
        ("key with a newline", ("x", "openai", "gpt", "sk\nabc", None), ["api_key"]),
        ("custom needs an address", ("x", "custom", "m", KEY, None), ["base_url"]),
        ("custom address ok", ("x", "custom", "m", KEY, "https://llm.example.org/v1"), []),
        ("custom with credentials", ("x", "custom", "m", KEY, "https://u:p@h/v1"), ["base_url"]),
        ("custom with a query", ("x", "custom", "m", KEY, "https://h/v1?token=1"), ["base_url"]),
        ("custom not http", ("x", "custom", "m", KEY, "file:///etc/passwd"), ["base_url"]),
        ("key to another address", ("x", "openai", "m", KEY, "https://evil.example"), ["base_url"]),
    ],
)
def test_requests_are_validated_field_by_field(
    label: str, args: tuple[str, str, str, str, str | None], bad: list[str]
) -> None:
    assert validate(*args) == bad, label


def test_every_provider_has_a_gateway_prefix() -> None:
    assert set(PROVIDERS) == {"openai", "anthropic", "openrouter", "custom"}
    assert PROVIDERS["custom"] == "openai"  # any OpenAI-compatible service


# --- the store ----------------------------------------------------------------------------------


def test_the_key_is_encrypted_at_rest_and_never_in_what_is_listed() -> None:
    r, _ = rig()
    put(r)
    with r.sessions() as s:
        row = s.get(LlmConnection, "cheap")
        assert row is not None
        assert KEY.encode() not in row.ciphertext and KEY.encode() not in row.nonce
        assert KEY not in repr([row.name, row.provider, row.model, row.base_url])
    listing = r.manager.models()
    assert [(m.name, m.provider, m.model, m.default) for m in listing] == [
        ("cheap", "openai", "gpt-4.1-mini", True)
    ]
    assert KEY not in repr(listing)


def test_the_key_is_bound_to_the_connection_so_a_copied_row_cannot_be_read() -> None:
    r, _ = rig()
    put(r)
    with r.sessions() as s:
        row = s.get(LlmConnection, "cheap")
        assert row is not None
        s.add(
            LlmConnection(
                name="stolen",
                provider="openai",
                model="m",
                ciphertext=row.ciphertext,
                nonce=row.nonce,
                key_version=row.key_version,
            )
        )
        s.commit()
        with pytest.raises(VaultError):
            store().entries(s)


def test_the_gateway_gets_the_key_and_the_provider_prefix() -> None:
    r, gateway = rig()
    put(r, "claude", provider="anthropic", model="claude-haiku-4-5", api_key="sk-ant-1")
    put(
        r,
        "mine",
        provider="custom",
        model="llama3",
        api_key="k2",
        base_url="https://llm.example.org/v1",
    )
    entries = {e.name: e for e in gateway.last}
    assert entries["claude"].model == "anthropic/claude-haiku-4-5"
    assert entries["claude"].api_key == "sk-ant-1" and entries["claude"].api_base is None
    assert entries["mine"].model == "openai/llama3"  # a custom service speaks the OpenAI protocol
    assert entries["mine"].api_base == "https://llm.example.org/v1"
    assert not entries["claude"].local and not entries["mine"].local


def test_the_include_file_prices_paid_models_by_the_gateway_not_at_zero() -> None:
    paid = LlmEntry("cheap", "openai/gpt-4.1-mini", None, KEY, local=False)
    local = LlmEntry("coder", "ollama_chat/q", "http://o:11434")
    parsed = yaml.safe_load(render_models([paid, local]))["model_list"]
    by_name = {m["model_name"]: m["litellm_params"] for m in parsed}
    assert by_name["cheap"] == {"model": "openai/gpt-4.1-mini", "api_key": KEY}
    assert by_name["coder"]["input_cost_per_token"] == 0
    assert KEY not in repr(paid)  # a key never ends up in a log line through a repr


def test_the_first_connection_becomes_the_default_and_the_next_does_not() -> None:
    r, _ = rig()
    put(r, "first")
    put(r, "second")
    assert {m.name: m.default for m in r.manager.models()} == {"first": True, "second": False}
    put(r, "third", make_default=True)
    assert {m.name for m in r.manager.models() if m.default} == {"third"}


def test_updating_a_connection_replaces_its_key() -> None:
    r, gateway = rig()
    put(r, api_key="old-key")
    put(r, api_key="new-key")
    assert [e.api_key for e in gateway.last] == ["new-key"]
    with r.sessions() as s:
        assert len(s.scalars(select(LlmConnection)).all()) == 1


def test_removing_the_default_goes_back_to_the_configured_one() -> None:
    r, gateway = rig()
    put(r, "a")
    put(r, "b")
    r.manager.set_default_model("b")
    r.manager.remove_model("b")
    with r.sessions() as s:
        assert s.get(PlatformState, 1).default_model is None  # type: ignore[union-attr]
    assert [e.name for e in gateway.last] == ["a"]
    with pytest.raises(ConnectionUnknown):
        r.manager.remove_model("b")


def test_a_default_must_be_a_connection() -> None:
    r, _ = rig()
    with pytest.raises(ConnectionUnknown):
        r.manager.set_default_model("ghost")
    put(r)
    r.manager.set_default_model(None)
    assert not any(m.default for m in r.manager.models())


def test_invalid_requests_change_nothing_and_do_not_touch_the_gateway() -> None:
    r, gateway = rig()
    with pytest.raises(ConnectionInvalid) as caught:
        put(r, "fake", provider="skynet", api_key="")
    assert set(caught.value.fields) == {"name", "provider", "api_key"}
    assert gateway.calls == [] and r.manager.models() == []


# --- the gateway decides --------------------------------------------------------------------------


def test_a_gateway_that_refuses_leaves_no_trace_of_the_change() -> None:
    r, gateway = rig()
    put(r, "good")
    gateway.fail = True
    with pytest.raises(RunnerError):
        put(r, "new", make_default=True)
    with pytest.raises(RunnerError):
        r.manager.remove_model("good")
    assert [(m.name, m.default) for m in r.manager.models()] == [("good", True)]


def test_a_first_connection_refused_by_the_gateway_is_not_kept_or_made_default() -> None:
    r, gateway = rig()
    gateway.fail = True
    with pytest.raises(RunnerError):
        put(r)
    assert r.manager.models() == []
    with r.sessions() as s:
        state = s.get(PlatformState, 1)
        assert state is None or state.default_model is None


def test_the_key_never_appears_in_a_log_even_when_the_gateway_fails(
    caplog: pytest.LogCaptureFixture,
) -> None:
    r, gateway = rig()
    gateway.fail = True
    with caplog.at_level(logging.DEBUG), pytest.raises(RunnerError):
        put(r, api_key="sk-very-secret-value")
    assert "sk-very-secret-value" not in caplog.text
    assert all("sk-very-secret-value" not in e.params.__repr__() for e in r.events())


# --- with the modules ----------------------------------------------------------------------------


def test_the_gateway_list_holds_the_backends_and_the_connections_together() -> None:
    r, gateway = rig()
    r.manager.install(["ollama"])
    put(r)
    assert {e.name for e in gateway.last} == {"coder-small", "cheap"}
    r.manager.uninstall(["ollama"])
    assert [e.name for e in gateway.last] == ["cheap"]  # removing a module keeps the connection
    r.manager.install(["ollama"])
    assert {e.name for e in gateway.last} == {"coder-small", "cheap"}


def test_recovery_gives_the_gateway_the_connections_again() -> None:
    r, gateway = rig()
    put(r)
    gateway.calls.clear()
    r.manager.recover()
    assert [e.name for e in gateway.last] == ["cheap"]


def test_a_model_change_waits_for_a_running_module_operation() -> None:
    r, gateway = rig()
    with r.manager._lock:  # a module install is running
        with pytest.raises(ManagerBusy):
            put(r)
        with pytest.raises(ManagerBusy):
            r.manager.remove_model("x")
        with pytest.raises(ManagerBusy):
            r.manager.set_default_model(None)
    assert gateway.calls == []
    put(r)  # and works as soon as it is over
    assert gateway.last


def test_without_a_connection_store_there_are_simply_no_models() -> None:
    r = Rig(modules=[OLLAMA])
    assert r.manager.models() == []
    with pytest.raises(RuntimeError):
        put(r)


def test_a_saved_key_is_known_to_the_log_redactor() -> None:
    redactor = Redactor()
    r = Rig(
        modules=[OLLAMA], llm=Gateway(), connections=ConnectionStore(Vault({1: MASTER}), redactor)
    )
    put(r, api_key="sk-redact-me-please-1234")
    assert "sk-redact-me-please-1234" not in redactor.redact(
        "calling with sk-redact-me-please-1234"
    )
    # and again after a restart: the key is registered when it is read back for the gateway
    fresh = Redactor()
    again = Rig(
        modules=[OLLAMA], llm=Gateway(), connections=ConnectionStore(Vault({1: MASTER}), fresh)
    )
    with r.sessions() as s:
        ConnectionStore(Vault({1: MASTER}), fresh).entries(s)
    assert "sk-redact-me-please-1234" not in fresh.redact("x sk-redact-me-please-1234 y")
    assert again.manager.models() == []
