"""`cobble models ...`: connect a model service with an API key, test it, choose the default.

Same rules as the Models tab in Settings: the module-manager keeps the key (encrypted), the
gateway uses it, nothing prints it back. The key is never an argument (it would show in the
process list and the shell history): it is typed at a hidden prompt or piped on stdin.
Exit codes: 0 done, 1 refused / failed, 2 usage, 3 the module-manager cannot be reached.
"""

from __future__ import annotations

import argparse
import getpass
import re
import sys
from collections.abc import Callable
from typing import Any, Protocol

from cobble.cli_modules import EXIT_UNAVAILABLE, Terminal, _refusal_text
from cobble.config import Settings
from cobble.i18n import t
from cobble.providers.module_manager import (
    HttpModuleManager,
    ModuleManagerRejected,
    ModuleManagerUnavailable,
)

PROVIDERS = ("openai", "anthropic", "openrouter", "custom")


class ModelsAPI(Protocol):
    def models(self) -> dict[str, Any]: ...
    def put_model(self, name: str, body: dict[str, Any]) -> dict[str, Any]: ...
    def delete_model(self, name: str) -> dict[str, Any]: ...
    def set_default_model(self, name: str) -> dict[str, Any]: ...


# Returns (ok, code): can the gateway reach the model with its key?
Probe = Callable[[str], tuple[bool, str]]


def connection_name(provider: str, model: str) -> str:
    """The name under which the gateway knows a connection (same rule as the Settings tab)."""
    slug = re.sub(r"[^a-z0-9._-]+", "-", f"{provider}-{model}".lower())
    slug = re.sub(r"^[^a-z0-9]+", "", slug)
    slug = re.sub(r"-{2,}", "-", slug)[:40]
    return re.sub(r"[-._]+$", "", slug)


def add_parser(sub: Any) -> None:
    models = sub.add_parser("models")
    actions = models.add_subparsers(dest="action", required=True)
    actions.add_parser("list")
    add = actions.add_parser("add")
    add.add_argument("provider", choices=PROVIDERS)
    add.add_argument("model")
    add.add_argument("--base-url", default=None, help="the service address (provider custom)")
    add.add_argument("--name", default=None, help="a name for this connection")
    add.add_argument("--no-default", action="store_true", help="do not use it by default")
    for name in ("remove", "default", "test"):
        actions.add_parser(name).add_argument("name")
    actions.choices["remove"].add_argument("--yes", action="store_true")


def _read_key(prompt: str) -> str:
    if sys.stdin.isatty():
        return getpass.getpass(prompt)
    return sys.stdin.readline().strip()


def _show(listing: dict[str, Any], term: Terminal, lang: str) -> None:
    models = listing.get("models", [])
    if not models:
        term.say(t("cli.models.empty", lang))
        return
    for m in models:
        mark = t("cli.models.default", lang) if m.get("default") else ""
        term.say(f"{m['name']:<40}  {m['provider']:<11} {m['model']}  {mark}".rstrip())


def _verdict(name: str, ok: bool, code: str, term: Terminal, lang: str) -> int:
    text = t(f"cli.models.test.{code}", lang)
    if ok:
        term.say(f"{name}: {text}")
        return 0
    term.warn(f"{name}: {text}")
    return 1


def run(
    args: argparse.Namespace,
    settings: Settings,
    *,
    api: ModelsAPI | None = None,
    term: Terminal | None = None,
    probe: Probe | None = None,
    read_key: Callable[[str], str] = _read_key,
) -> int:
    lang = settings.lang
    term = term or Terminal()
    api = api or HttpModuleManager.from_settings(settings)
    try:
        if args.action == "list":
            _show(api.models(), term, lang)
            return 0
        if args.action == "default":
            api.set_default_model(args.name)
            term.say(t("cli.models.now_default", lang, name=args.name))
            return 0
        if args.action == "remove":
            if not (
                args.yes
                or term.confirm(t("cli.models.remove_question", lang, name=args.name), lang)
            ):
                term.say(t("cli.modules.declined", lang))
                return 1
            api.delete_model(args.name)
            term.say(t("cli.models.removed", lang, name=args.name))
            return 0
        if args.action == "test":
            return _test(args.name, term, lang, settings, probe)
        return _add(args, api, term, lang, settings, probe, read_key)
    except ModuleManagerUnavailable:
        term.warn(t("cli.modules.unavailable", lang))
        return EXIT_UNAVAILABLE
    except ModuleManagerRejected as exc:
        term.warn(_refusal_text(exc, lang))
        return 1


def _add(
    args: argparse.Namespace,
    api: ModelsAPI,
    term: Terminal,
    lang: str,
    settings: Settings,
    probe: Probe | None,
    read_key: Callable[[str], str],
) -> int:
    if args.provider == "custom" and not args.base_url:
        term.warn(t("cli.models.need_base_url", lang))
        return 2
    name = args.name or connection_name(args.provider, args.model)
    key = read_key(t("cli.models.key_prompt", lang)).strip()
    if not key:
        term.warn(t("cli.models.empty_key", lang))
        return 2
    term.say(t("cli.models.working", lang))
    api.put_model(
        name,
        {
            "provider": args.provider,
            "model": args.model,
            "api_key": key,
            "base_url": args.base_url if args.provider == "custom" else None,
            "make_default": not args.no_default,
        },
    )
    term.say(t("cli.models.added", lang, name=name))
    return _test(name, term, lang, settings, probe)


def _test(name: str, term: Terminal, lang: str, settings: Settings, probe: Probe | None) -> int:
    ok, code = (probe or _gateway_probe(settings))(name)
    return _verdict(name, ok, code, term, lang)


def _gateway_probe(settings: Settings) -> Probe:
    from cobble.db import make_engine, make_session_factory
    from cobble.router.gateway import LiteLLMGateway

    def run_probe(name: str) -> tuple[bool, str]:
        gateway = LiteLLMGateway(
            settings.litellm_url,
            settings.litellm_key,
            make_session_factory(make_engine(settings.database_url)),
        )
        result = gateway.probe(name)
        return result.ok, result.code

    return run_probe
