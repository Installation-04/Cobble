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
    preset = actions.add_parser("preset", help="apply a ready-made set of routes")
    preset.add_argument("id", nargs="?", help="economical-local or balanced (none: list them)")
    for slot in ("local", "cheap", "strong"):
        preset.add_argument(f"--{slot}", default=None, help=f"the model for the {slot} slot")
    route = actions.add_parser("route", help="which models each role tries, in order")
    route.add_argument("role", nargs="?", help="planner, test-writer, worker, reviewer, escalation")
    route.add_argument("names", nargs="*", help="models to try, best first (none: show the role)")
    route.add_argument("--clear", action="store_true", help="make the role follow the default")


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
    routes: RoutesStore | None = None,
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
        if args.action == "preset":
            return _preset(args, api, term, lang, settings, routes)
        if args.action == "route":
            return _route(args, api, term, lang, settings, routes)
        return _add(args, api, term, lang, settings, probe, read_key)
    except ModuleManagerUnavailable:
        term.warn(t("cli.modules.unavailable", lang))
        return EXIT_UNAVAILABLE
    except ModuleManagerRejected as exc:
        term.warn(_refusal_text(exc, lang))
        return 1


class RoutesStore(Protocol):
    def get(self) -> dict[str, list[str]]: ...
    def put(self, routes: dict[str, list[str]]) -> None: ...


class DbRoutes:
    """The routes as the core stores them (`platform_state.role_routes`)."""

    def __init__(self, settings: Settings) -> None:
        from cobble.db import make_engine, make_session_factory

        self._sessions = make_session_factory(make_engine(settings.database_url))

    def get(self) -> dict[str, list[str]]:
        from cobble.db.models import PlatformState

        with self._sessions() as session:
            state = session.get(PlatformState, 1)
            return {k: list(v) for k, v in (state.role_routes or {}).items()} if state else {}

    def put(self, routes: dict[str, list[str]]) -> None:
        from cobble.db.models import PlatformState

        with self._sessions() as session:
            state = session.get(PlatformState, 1)
            if state is None:
                state = PlatformState(id=1)
                session.add(state)
            state.role_routes = routes or None
            session.commit()


def _preset(
    args: argparse.Namespace,
    api: ModelsAPI,
    term: Terminal,
    lang: str,
    settings: Settings,
    store: RoutesStore | None,
) -> int:
    from cobble.router.presets import BY_ID, PRESETS, resolve

    listing = api.models()
    local = listing.get("local", [])
    known = {m["name"] for m in listing.get("models", [])} | {m["name"] for m in local}
    known.add(settings.default_model)
    slots: dict[str, str | None] = {
        "local": local[0]["name"] if local else None,
        "cheap": None,
        "strong": listing.get("default") or settings.default_model,
    }
    for slot in slots:
        chosen = getattr(args, slot)
        if chosen:
            slots[slot] = chosen
    unknown = sorted({name for name in slots.values() if name and name not in known})
    if unknown:
        term.warn(t("cli.models.route.unknown", lang, names=", ".join(unknown)))
        return 2
    if args.id is None:
        for preset in PRESETS:
            outcome = resolve(preset, slots)
            state = (
                t("cli.models.preset.ready", lang)
                if outcome.available
                else t("cli.models.preset.needs", lang, slots=", ".join(outcome.missing))
            )
            term.say(f"{preset.id:<18} {t(f'cli.models.preset.name.{preset.id}', lang)}: {state}")
        return 0
    chosen_preset = BY_ID.get(args.id)
    if chosen_preset is None:
        ids = ", ".join(BY_ID)
        term.warn(t("cli.models.preset.unknown", lang, id=args.id, ids=ids))
        return 2
    outcome = resolve(chosen_preset, slots)
    if not outcome.available:
        needs = t("cli.models.preset.needs", lang, slots=", ".join(outcome.missing))
        term.warn(f"{args.id}: {needs}")
        return 1
    (store or DbRoutes(settings)).put(outcome.routes)
    term.say(t("cli.models.preset.applied", lang, id=args.id))
    for role, chain in outcome.routes.items():
        term.say(f"  {role:<12} {' → '.join(chain)}")
    return 0


def _route(
    args: argparse.Namespace,
    api: ModelsAPI,
    term: Terminal,
    lang: str,
    settings: Settings,
    store: RoutesStore | None,
) -> int:
    from cobble.router.policy import MAX_CHAIN, ROLES

    roles = [role.value for role in ROLES]
    current = (store or DbRoutes(settings)).get()
    if args.role is None:
        for role in roles:
            chain = (
                " → ".join(current[role])
                if role in current
                else t("cli.models.route.default", lang)
            )
            term.say(f"{role:<12} {chain}")
        return 0
    if args.role not in roles:
        term.warn(t("cli.models.route.bad_role", lang, role=args.role, roles=", ".join(roles)))
        return 2
    if not args.names and not args.clear:
        chain = (
            " → ".join(current[args.role])
            if args.role in current
            else t("cli.models.route.default", lang)
        )
        term.say(f"{args.role}: {chain}")
        return 0
    names = list(dict.fromkeys(args.names))
    if args.clear:
        names = []
    known = {m["name"] for m in api.models().get("models", [])} | {settings.default_model}
    unknown = [n for n in names if n not in known]
    if unknown or len(names) > MAX_CHAIN:
        key = "unknown" if unknown else "too_long"
        term.warn(t(f"cli.models.route.{key}", lang, names=", ".join(unknown), max=MAX_CHAIN))
        return 2
    updated = {**current, args.role: names}
    (store or DbRoutes(settings)).put({r: c for r, c in updated.items() if c})
    if names:
        term.say(t("cli.models.route.set", lang, role=args.role, chain=" → ".join(names)))
    else:
        term.say(t("cli.models.route.cleared", lang, role=args.role))
    return 0


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
