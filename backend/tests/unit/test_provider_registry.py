"""Modules that run become providers; unknown modules are ignored; secrets stay hidden."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from cobble.providers.module_manager import HttpModuleManager, ModuleManagerUnavailable
from cobble.providers.registry import Connection, ProviderRegistry, default_registry
from cobble.providers.settings import PackSettings

BASE = PackSettings(forgejo_owner="cobble-bot")


def conn(module_id: str, provides: list[str], **secrets: str) -> Connection:
    return Connection(module_id, f"http://{module_id}:1", tuple(provides), secrets)


def test_git_and_ci_modules_become_providers_with_their_own_address_and_token() -> None:
    connections = {
        "forgejo": conn("forgejo", ["git"], api_token="git-token"),
        "woodpecker": conn("woodpecker", ["ci"], api_token="ci-token"),
    }
    built = default_registry().build(connections, BASE)
    assert built is not None
    assert (built.git_module, built.ci_module) == ("forgejo", "woodpecker")
    ci_settings = built.ci.settings  # type: ignore[attr-defined]
    assert ci_settings.woodpecker_url == "http://woodpecker:1/ci"
    assert ci_settings.woodpecker_token.get_secret_value() == "ci-token"
    git_settings = built.git.settings  # type: ignore[attr-defined]
    assert git_settings.forgejo_url == "http://forgejo:1"
    assert git_settings.forgejo_token.get_secret_value() == "git-token"
    assert git_settings.forgejo_owner == "cobble-bot"  # the rest of the base settings is kept
    assert built.git.ci is built.ci  # type: ignore[attr-defined]


@pytest.mark.parametrize("missing", ["forgejo", "woodpecker"])
def test_without_git_or_ci_nothing_is_built(missing: str) -> None:
    connections = {
        "forgejo": conn("forgejo", ["git"], api_token="t"),
        "woodpecker": conn("woodpecker", ["ci"], api_token="t"),
    }
    del connections[missing]
    assert default_registry().build(connections, BASE) is None


def test_a_module_without_an_adapter_is_ignored() -> None:
    connections = {
        "mystery": conn("mystery", ["git", "ci"], api_token="t"),
        "woodpecker": conn("woodpecker", ["ci"], api_token="t"),
    }
    assert default_registry().build(connections, BASE) is None


def test_the_first_module_with_an_adapter_wins_in_a_stable_order() -> None:
    registry = ProviderRegistry()
    made: list[str] = []

    def ci_factory(c: Connection, _b: PackSettings) -> Any:
        made.append(c.module_id)
        return object()

    def git_factory(c: Connection, _b: PackSettings, _ci: Any) -> Any:
        made.append(c.module_id)
        return object()

    registry.register_ci("zeta-ci", ci_factory)
    registry.register_ci("alpha-ci", ci_factory)
    registry.register_git("g", git_factory)
    built = registry.build(
        {
            "zeta-ci": conn("zeta-ci", ["ci"]),
            "alpha-ci": conn("alpha-ci", ["ci"]),
            "g": conn("g", ["git"]),
        },
        BASE,
    )
    assert built is not None and built.ci_module == "alpha-ci"
    assert made == ["alpha-ci", "g"]


def test_a_connection_never_prints_its_secrets() -> None:
    c = Connection.from_json(
        "forgejo",
        {"url": "http://f:3000", "provides": ["git"], "secrets": {"api_token": "hunter2"}},
    )
    assert "hunter2" not in repr(c)
    assert c.secrets == {"api_token": "hunter2"} and c.provides == ("git",)
    assert Connection.from_json("x", {}).url == ""
    assert SecretStr("a") != SecretStr("b")  # sanity: settings keep secrets as SecretStr


def test_the_client_reads_connections_and_hides_transport_errors() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/connections"
        assert request.headers["Authorization"] == "Bearer tok"
        return httpx.Response(200, json={"connections": {"forgejo": {"url": "u"}}})

    client = HttpModuleManager("http://m:1", "tok", transport=httpx.MockTransport(handler))
    assert client.connections() == {"forgejo": {"url": "u"}}

    def down(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused tok")

    broken = HttpModuleManager("http://m:1", "tok", transport=httpx.MockTransport(down))
    with pytest.raises(ModuleManagerUnavailable) as caught:
        broken.connections()
    assert "tok" not in str(caught.value)
