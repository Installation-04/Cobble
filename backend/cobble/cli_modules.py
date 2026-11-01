"""`cobble modules ...`: list, install and uninstall modules from a terminal.

It asks the module-manager (through the same client as the API); it never touches Docker and
never prints a secret value. Exit codes: 0 done, 1 refused / failed / declined, 2 usage,
3 the module-manager cannot be reached (the `cobble` wrapper adds a hint for that one).
"""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from typing import Any, Protocol, TextIO

from cobble.config import Settings
from cobble.i18n import t
from cobble.providers.module_manager import (
    HttpModuleManager,
    ModuleManagerRejected,
    ModuleManagerUnavailable,
)

EXIT_UNAVAILABLE = 3
POLL_S = 2.0
PATIENCE_S = 3600.0  # an install can pull images and models: be patient, but not forever


class ManagerAPI(Protocol):
    def catalog(self) -> dict[str, Any]: ...
    def plan(self, body: dict[str, Any]) -> dict[str, Any]: ...
    def start_operation(self, body: dict[str, Any]) -> str: ...
    def operation(self, operation_id: str) -> dict[str, Any]: ...
    def secret_status(self, module_id: str) -> dict[str, bool]: ...
    def packs(self) -> dict[str, Any]: ...


def add_parser(sub: Any) -> None:
    modules = sub.add_parser("modules")
    actions = modules.add_subparsers(dest="action", required=True)
    actions.add_parser("list")
    actions.add_parser("packs")
    status = actions.add_parser("status")
    status.add_argument("module")
    for name in ("install", "uninstall"):
        action = actions.add_parser(name)
        action.add_argument("modules", nargs="*" if name == "install" else "+")
        action.add_argument("--yes", action="store_true", help="do not ask for confirmation")
    install = actions.choices["install"]
    install.add_argument(
        "--pack", metavar="PACK", help="install a starter pack (see `cobble modules packs`)"
    )
    install.add_argument(
        "--choose",
        action="append",
        default=[],
        metavar="CAPABILITY=MODULE",
        help="which module provides a capability when several can",
    )
    install.add_argument("--replace", action="store_true", help="replace an exclusive provider")


class Terminal:
    """Where the command talks: output, errors, and asking yes/no (no answer means no)."""

    def __init__(
        self,
        out: TextIO | None = None,
        err: TextIO | None = None,
        ask: Callable[[str], str] | None = None,
    ) -> None:
        self.out = out or sys.stdout
        self.err = err or sys.stderr
        self._ask = ask or input

    def say(self, text: str = "") -> None:
        print(text, file=self.out, flush=True)

    def warn(self, text: str) -> None:
        print(text, file=self.err, flush=True)

    def confirm(self, question: str, lang: str) -> bool:
        try:
            answer = self._ask(f"{question} {t('cli.modules.yes_no', lang)} ")
        except EOFError:
            return False
        return answer.strip().lower() in ("y", "yes", "o", "oui")


def _state_label(state: Mapping[str, Any] | None, lang: str) -> str:
    if state is None:
        return t("cli.modules.state.none", lang)
    return t(f"cli.modules.state.{state.get('state', 'unknown')}", lang)


def _problems(hardware: Mapping[str, Any], lang: str) -> str:
    return "; ".join(
        t("cli.modules.problem", lang, code=p["code"], needed=p["needed"], have=p["have"])
        for p in hardware.get("problems", [])
    )


def _fit(entry: Mapping[str, Any], lang: str) -> str:
    hardware = entry.get("hardware", {})
    if hardware.get("ok"):
        variant = hardware.get("variant")
        return (
            t("cli.modules.fit.ok_variant", lang, variant=variant)
            if variant
            else t("cli.modules.fit.ok", lang)
        )
    return t("cli.modules.fit.no", lang, problems=_problems(hardware, lang))


def _list(api: ManagerAPI, term: Terminal, lang: str) -> int:
    modules = api.catalog().get("modules", [])
    if not modules:
        term.say(t("cli.modules.empty", lang))
        return 0
    for entry in modules:
        term.say(
            "  ".join(
                [
                    f"{entry['id']:<14}",
                    f"{entry['version']:<10}",
                    f"{_state_label(entry.get('installed'), lang):<16}",
                    _fit(entry, lang),
                ]
            )
        )
    return 0


def _pack_problems(pack: Mapping[str, Any], lang: str) -> str:
    parts = []
    for problem in pack.get("fit", {}).get("problems", []):
        text = t(
            "cli.modules.problem",
            lang,
            code=problem["code"],
            needed=problem["needed"],
            have=problem["have"],
        )
        parts.append(f"{problem['module']}: {text}" if problem.get("module") else text)
    return "; ".join(parts)


def _packs(api: ManagerAPI, term: Terminal, lang: str) -> int:
    body = api.packs()
    packs = body.get("packs", [])
    for pack_id, issues in sorted(body.get("problems", {}).items()):
        term.warn(t("cli.modules.pack.ignored", lang, pack=pack_id, problems="; ".join(issues)))
    if not packs:
        term.say(t("cli.modules.pack.empty", lang))
        return 0
    for pack in packs:
        marks = []
        if pack.get("recommended"):
            marks.append(t("cli.modules.pack.recommended", lang))
        marks.append(
            t(
                "cli.modules.pack.installed" if pack.get("installed") else "cli.modules.pack.todo",
                lang,
            )
        )
        fit = (
            t("cli.modules.fit.ok", lang)
            if pack["fit"]["ok"]
            else t("cli.modules.fit.no", lang, problems=_pack_problems(pack, lang))
        )
        name = pack["name"].get(lang) or pack["name"].get("en", "")
        term.say(f"{pack['id']:<12} {name}  [{', '.join(marks)}]  {fit}")
        description = pack["description"].get(lang) or pack["description"].get("en", "")
        term.say(f"             {description}")
        term.say(
            f"             {t('cli.modules.pack.modules', lang)}: {', '.join(pack['modules'])}"
        )
    return 0


def _pack_modules(
    api: ManagerAPI, term: Terminal, lang: str, pack_id: str, extra: list[str]
) -> list[str] | None:
    """The modules of a pack (and any named next to it), or None when it cannot be installed."""
    pack = next((p for p in api.packs().get("packs", []) if p["id"] == pack_id), None)
    if pack is None:
        term.warn(t("cli.modules.pack.unknown", lang, pack=pack_id))
        return None
    if not pack["fit"]["ok"]:
        term.warn(
            t("cli.modules.pack.no_fit", lang, pack=pack_id, problems=_pack_problems(pack, lang))
        )
        return None
    return list(dict.fromkeys([*pack["modules"], *extra]))


def _status(api: ManagerAPI, term: Terminal, lang: str, module_id: str) -> int:
    entry = next((m for m in api.catalog().get("modules", []) if m["id"] == module_id), None)
    if entry is None:
        term.warn(t("cli.modules.refused.module_unknown", lang, module=module_id))
        return 1
    installed = entry.get("installed")
    description = entry.get("description", {})
    term.say(f"{entry['name']} {entry['version']} ({entry['id']})")
    term.say(description.get(lang) or description.get("en", ""))
    term.say(f"{t('cli.modules.label.state', lang)}: {_state_label(installed, lang)}")
    if installed and installed.get("variant"):
        term.say(f"{t('cli.modules.label.variant', lang)}: {installed['variant']}")
    if installed and installed.get("error"):
        term.say(
            f"{t('cli.modules.label.error', lang)}: {_code_text(str(installed['error']), lang)}"
        )
    term.say(f"{t('cli.modules.label.fit', lang)}: {_fit(entry, lang)}")
    for label, key in (("provides", "provides"), ("requires", "requires")):
        values = entry.get(key) or []
        if values:
            term.say(f"{t(f'cli.modules.label.{label}', lang)}: {', '.join(values)}")
    if installed:  # only whether each secret is set, never its value
        try:
            secrets = api.secret_status(module_id)
        except ModuleManagerRejected:
            secrets = {}
        if secrets:
            shown = ", ".join(
                f"{key} ({t('cli.modules.secret.set' if ok else 'cli.modules.secret.unset', lang)})"
                for key, ok in sorted(secrets.items())
            )
            term.say(f"{t('cli.modules.label.secrets', lang)}: {shown}")
    return 0


def _code_text(code: str, lang: str) -> str:
    key = f"cli.modules.code.{code}"
    text = t(key, lang)
    return text if text != key else t("cli.modules.code.unknown", lang, code=code)


_REFUSAL_PARAMS = ("module", "capability", "candidates", "cascade", "modules", "problems")


def _refusal_text(exc: ModuleManagerRejected, lang: str) -> str:
    """The manager's refusal in the user's language (its code and parameters are stable)."""
    params = dict.fromkeys(_REFUSAL_PARAMS, "")
    params.update({key: _join(value, lang) for key, value in exc.params.items()})
    key = f"cli.modules.refused.{exc.code}"
    text = t(key, lang, **params)
    if text == key:  # a code this version does not know
        return t("cli.modules.refused.unknown", lang, code=exc.code)
    return text


def _join(value: Any, lang: str) -> str:
    if isinstance(value, list):
        return ", ".join(_join(item, lang) for item in value)
    if isinstance(value, dict):  # a hardware problem
        return t(
            "cli.modules.problem",
            lang,
            code=value.get("code"),
            needed=value.get("needed"),
            have=value.get("have"),
        )
    return str(value)


def _describe_plan(plan: Mapping[str, Any], term: Terminal, lang: str) -> None:
    steps = plan.get("steps", [])
    for step in steps:
        term.say(f"  {t(f'cli.modules.step.{step["action"]}', lang)} {step['module']}")
    if plan.get("auto_added"):
        term.say(t("cli.modules.plan.auto_added", lang, modules=", ".join(plan["auto_added"])))
    if plan.get("auto_removed"):
        term.say(t("cli.modules.plan.auto_removed", lang, modules=", ".join(plan["auto_removed"])))


def _parse_choices(values: Sequence[str]) -> dict[str, str] | None:
    choices: dict[str, str] = {}
    for value in values:
        capability, sep, module = value.partition("=")
        if not sep or not capability or not module:
            return None
        choices[capability] = module
    return choices


def _change(
    api: ManagerAPI,
    term: Terminal,
    lang: str,
    action: str,
    modules: list[str],
    *,
    choices: dict[str, str],
    replace: bool,
    yes: bool,
    sleep: Callable[[float], None],
    clock: Callable[[], float],
) -> int:
    body: dict[str, Any] = {
        "action": action,
        "modules": modules,
        "choices": choices,
        "replace": replace,
        "confirm_cascade": False,
    }
    try:
        try:
            plan = api.plan(body)
        except ModuleManagerRejected as exc:
            if exc.code != "module_needs_confirmation":
                raise
            # Removing this also removes modules that depend on it: say so, ask for it.
            term.warn(_refusal_text(exc, lang))
            if not (yes or term.confirm(t("cli.modules.cascade_question", lang), lang)):
                term.say(t("cli.modules.declined", lang))
                return 1
            body["confirm_cascade"] = True
            plan = api.plan(body)
        if not plan.get("steps"):
            term.say(t("cli.modules.nothing_to_do", lang))
            return 0
        term.say(t("cli.modules.plan.title", lang))
        _describe_plan(plan, term, lang)
        if not (yes or term.confirm(t("cli.modules.question", lang), lang)):
            term.say(t("cli.modules.declined", lang))
            return 1
        operation_id = api.start_operation(body)
        return _follow(api, term, lang, operation_id, action, sleep, clock)
    except ModuleManagerRejected as exc:
        term.warn(_refusal_text(exc, lang))
        return 1
    except ModuleManagerUnavailable:
        term.warn(t("cli.modules.unavailable", lang))
        return EXIT_UNAVAILABLE


def _follow(
    api: ManagerAPI,
    term: Terminal,
    lang: str,
    operation_id: str,
    action: str,
    sleep: Callable[[float], None],
    clock: Callable[[], float],
) -> int:
    started = clock()
    term.say(
        t("cli.modules.working" if action == "install" else "cli.modules.working_remove", lang)
    )
    while True:
        operation = api.operation(operation_id)
        state = operation.get("state")
        if state == "done":
            term.say(t("cli.modules.done", lang))
            return 0
        if state == "failed":
            error = operation.get("error") or {}
            term.warn(
                t(
                    "cli.modules.failed",
                    lang,
                    module=error.get("module") or "-",
                    step=error.get("step") or "-",
                    reason=_code_text(str(error.get("code", "unknown")), lang),
                )
            )
            if error.get("rolled_back"):
                term.warn(
                    t("cli.modules.rolled_back", lang, modules=", ".join(error["rolled_back"]))
                )
            if error.get("partial"):
                term.warn(t("cli.modules.partial", lang))
            return 1
        if clock() - started > PATIENCE_S:
            term.warn(t("cli.modules.still_running", lang, id=operation_id))
            return 1
        sleep(POLL_S)


def run(
    args: argparse.Namespace,
    settings: Settings,
    *,
    api: ManagerAPI | None = None,
    term: Terminal | None = None,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> int:
    lang = settings.lang
    term = term or Terminal()
    api = api or HttpModuleManager.from_settings(settings)
    try:
        if args.action == "list":
            return _list(api, term, lang)
        if args.action == "packs":
            return _packs(api, term, lang)
        if args.action == "status":
            return _status(api, term, lang, args.module)
        choices = _parse_choices(getattr(args, "choose", []))
        if choices is None:
            term.warn(t("cli.modules.bad_choose", lang))
            return 2
        modules = list(args.modules)
        if getattr(args, "pack", None):
            expanded = _pack_modules(api, term, lang, args.pack, modules)
            if expanded is None:
                return 1
            modules = expanded
        if not modules:
            term.warn(t("cli.modules.pack.nothing", lang))
            return 2
        return _change(
            api,
            term,
            lang,
            args.action,
            modules,
            choices=choices,
            replace=getattr(args, "replace", False),
            yes=args.yes,
            sleep=sleep,
            clock=clock,
        )
    except ModuleManagerUnavailable:
        term.warn(t("cli.modules.unavailable", lang))
        return EXIT_UNAVAILABLE
    except ModuleManagerRejected as exc:
        term.warn(_refusal_text(exc, lang))
        return 1
