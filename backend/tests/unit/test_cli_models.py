"""`cobble models`: connect, test, choose; the key is never an argument and never printed."""

from __future__ import annotations

import argparse
import io
from typing import Any

from cobble.cli_models import add_parser, connection_name, run
from cobble.cli_modules import EXIT_UNAVAILABLE, Terminal
from cobble.config import Settings
from cobble.providers.module_manager import ModuleManagerRejected, ModuleManagerUnavailable

SECRET = "sk-very-secret-key-456"


class FakeModels:
    def __init__(self) -> None:
        self.items: list[dict[str, Any]] = []
        self.bodies: list[tuple[str, dict[str, Any]]] = []
        self.error: Exception | None = None

    def _check(self) -> None:
        if self.error:
            raise self.error

    def put_model(self, name: str, body: dict[str, Any]) -> dict[str, Any]:
        self._check()
        self.bodies.append((name, body))
        self.items = [
            {
                "name": name,
                "provider": body["provider"],
                "model": body["model"],
                "default": body["make_default"],
            }
        ]
        return {"models": self.items}

    def delete_model(self, name: str) -> dict[str, Any]:
        self._check()
        self.items = []
        return {"models": []}

    def set_default_model(self, name: str) -> dict[str, Any]:
        self._check()
        return {"models": self.items}


class API(FakeModels):
    def models(self) -> dict[str, Any]:  # type: ignore[override]
        self._check()
        return {"models": self.items}


def parse(*argv: str) -> argparse.Namespace:
    root = argparse.ArgumentParser()
    add_parser(root.add_subparsers(dest="command", required=True))
    return root.parse_args(["models", *argv])


def go(
    *argv: str, api: API | None = None, lang: str = "en", answer: str = "n", probe_code: str = "ok"
):
    api = api or API()
    out, err = io.StringIO(), io.StringIO()
    term = Terminal(out, err, ask=lambda _q: answer)
    settings = Settings(lang=lang)
    code = run(
        parse(*argv),
        settings,
        api=api,
        term=term,
        probe=lambda name: (probe_code == "ok", probe_code),
        read_key=lambda _prompt: SECRET,
    )
    return code, out.getvalue(), err.getvalue(), api


def test_name_follows_the_same_rule_as_the_settings_tab() -> None:
    assert connection_name("openai", "gpt-4.1-mini") == "openai-gpt-4.1-mini"
    assert connection_name("custom", "x" * 100) == connection_name("custom", "x" * 100)
    assert len(connection_name("custom", "x" * 100)) <= 40
    assert connection_name("openrouter", "Meta/Llama 3 !!").startswith("openrouter-meta-llama-3")


def test_add_sends_the_key_once_tests_it_and_never_prints_it() -> None:
    code, out, err, api = go("add", "openai", "gpt-4.1-mini")
    assert code == 0
    name, body = api.bodies[0]
    assert name == "openai-gpt-4.1-mini"
    assert body["api_key"] == SECRET and body["make_default"] is True and body["base_url"] is None
    assert "the key works" in out
    assert SECRET not in out + err


def test_a_rejected_key_is_explained_and_fails() -> None:
    code, out, err, _ = go("add", "openai", "gpt-4.1-mini", probe_code="auth_failed")
    assert code == 1
    assert "refused the key" in err
    assert SECRET not in out + err


def test_custom_needs_an_address_and_sends_it() -> None:
    code, _, err, _ = go("add", "custom", "llama3")
    assert code == 2 and "--base-url" in err
    code, _, _, api = go("add", "custom", "llama3", "--base-url", "http://x:1/v1", "--no-default")
    assert code == 0
    assert api.bodies[0][1]["base_url"] == "http://x:1/v1"
    assert api.bodies[0][1]["make_default"] is False


def test_list_remove_and_default() -> None:
    api = API()
    go("add", "openai", "gpt-4.1-mini", api=api)
    code, out, _, _ = go("list", api=api)
    assert code == 0 and "openai-gpt-4.1-mini" in out and "(default)" in out
    assert go("default", "openai-gpt-4.1-mini", api=api)[0] == 0
    # removing asks first: no answer means no
    code, _, _, _ = go("remove", "openai-gpt-4.1-mini", api=api)
    assert code == 1 and api.items
    code, _, _, _ = go("remove", "openai-gpt-4.1-mini", "--yes", api=api)
    assert code == 0 and not api.items
    assert "demo" in go("list", api=api)[1]


def test_french_and_failures() -> None:
    assert "clé fonctionne" in go("add", "openai", "gpt-4.1-mini", lang="fr")[1]
    api = API()
    api.error = ModuleManagerUnavailable()
    assert go("list", api=api)[0] == EXIT_UNAVAILABLE
    api.error = ModuleManagerRejected(502, "model_gateway_failed", {})
    code, _, err, _ = go("default", "x", api=api)
    assert code == 1 and "nothing was changed" in err
    api.error = ModuleManagerRejected(404, "model_unknown", {"name": "zz"})
    assert "zz" in go("default", "zz", api=api)[2]
