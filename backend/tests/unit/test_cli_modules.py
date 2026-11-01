"""`cobble modules`: what it shows, what it asks, what it never does."""

from __future__ import annotations

import argparse
import io
import json
import re
from pathlib import Path
from typing import Any

import pytest

from cobble import cli
from cobble.cli_modules import (
    EXIT_UNAVAILABLE,
    PATIENCE_S,
    Terminal,
    add_parser,
    run,
)
from cobble.config import Settings
from cobble.providers.module_manager import ModuleManagerRejected, ModuleManagerUnavailable

ROOT = Path(__file__).resolve().parents[3]


def entry(module_id: str, state: dict[str, Any] | None = None, **extra: Any) -> dict[str, Any]:
    return {
        "id": module_id,
        "name": module_id.title(),
        "version": "1.0.0",
        "description": {"en": f"{module_id} in English", "fr": f"{module_id} en français"},
        "provides": [],
        "requires": [],
        "hardware": {"ok": True, "variant": None, "problems": []},
        "installed": state,
        **extra,
    }


def plan(*steps: tuple[str, str], auto_added: list[str] | None = None) -> dict[str, Any]:
    return {
        "steps": [{"action": a, "module": m} for a, m in steps],
        "auto_added": auto_added or [],
        "auto_removed": [],
    }


class FakeAPI:
    def __init__(self) -> None:
        self.modules: list[dict[str, Any]] = []
        self.plans: list[Any] = []  # dicts to return, exceptions to raise
        self.operations: list[dict[str, Any]] = []
        self.secrets: dict[str, bool] = {}
        self.bodies: list[dict[str, Any]] = []
        self.started: list[dict[str, Any]] = []
        self.start_error: Exception | None = None
        self.down = False
        self.pack_body: dict[str, Any] = {"packs": [], "problems": {}, "recommended": None}

    def _check(self) -> None:
        if self.down:
            raise ModuleManagerUnavailable("down")

    def catalog(self) -> dict[str, Any]:
        self._check()
        return {"modules": self.modules}

    def plan(self, body: dict[str, Any]) -> dict[str, Any]:
        self._check()
        self.bodies.append(dict(body))
        item = self.plans.pop(0)
        if isinstance(item, Exception):
            raise item
        return item  # type: ignore[no-any-return]

    def start_operation(self, body: dict[str, Any]) -> str:
        self._check()
        if self.start_error:
            raise self.start_error
        self.started.append(dict(body))
        return "op1"

    def operation(self, operation_id: str) -> dict[str, Any]:
        self._check()
        return self.operations.pop(0) if len(self.operations) > 1 else self.operations[0]

    def secret_status(self, module_id: str) -> dict[str, bool]:
        return self.secrets

    def packs(self) -> dict[str, Any]:
        self._check()
        return self.pack_body


class Rig:
    def __init__(self, answers: list[str] | None = None, lang: str = "en") -> None:
        self.api = FakeAPI()
        self.out, self.err = io.StringIO(), io.StringIO()
        self.asked: list[str] = []
        self.answers = list(answers or [])
        self.settings = Settings(lang=lang)
        self.sleeps: list[float] = []
        self.now = 0.0

        def ask(prompt: str) -> str:
            self.asked.append(prompt)
            if not self.answers:
                raise EOFError
            return self.answers.pop(0)

        self.term = Terminal(self.out, self.err, ask)

    def go(self, *argv: str) -> int:
        parser = argparse.ArgumentParser()
        add_parser(parser.add_subparsers(dest="command", required=True))
        args = parser.parse_args(["modules", *argv])

        def sleep(seconds: float) -> None:
            self.sleeps.append(seconds)
            self.now += seconds

        return run(
            args, self.settings, api=self.api, term=self.term, sleep=sleep, clock=lambda: self.now
        )

    @property
    def said(self) -> str:
        return self.out.getvalue()

    @property
    def warned(self) -> str:
        return self.err.getvalue()


def rejected(code: str, status: int = 409, **params: Any) -> ModuleManagerRejected:
    return ModuleManagerRejected(status, code, params)


DONE = {"state": "done", "error": None}
RUNNING = {"state": "running", "error": None}


# --- list and status ----------------------------------------------------------------------------


def test_list_shows_each_module_with_its_state_and_fit() -> None:
    rig = Rig()
    rig.api.modules = [
        entry("forgejo", {"state": "running", "variant": None}),
        entry("ollama", None, hardware={"ok": True, "variant": "cpu", "problems": []}),
        entry(
            "big",
            None,
            hardware={
                "ok": False,
                "variant": None,
                "problems": [{"code": "ram_mb", "needed": 8192, "have": 4096}],
            },
        ),
    ]
    assert rig.go("list") == 0
    lines = rig.said.splitlines()
    assert "installed" in lines[0] and "fits this machine" in lines[0]
    assert "not installed" in lines[1] and "flavour: cpu" in lines[1]
    assert "does not fit" in lines[2] and "ram_mb: needs 8192, has 4096" in lines[2]


def test_list_in_french_and_an_empty_catalogue() -> None:
    rig = Rig(lang="fr")
    rig.api.modules = [entry("forgejo", {"state": "running"})]
    rig.go("list")
    assert "installé" in rig.said and "convient à cette machine" in rig.said
    empty = Rig()
    empty.go("list")
    assert "catalogue is empty" in empty.said


def test_status_shows_details_and_only_whether_secrets_are_set() -> None:
    rig = Rig()
    rig.api.modules = [
        entry(
            "forgejo",
            {"state": "running", "variant": "cpu", "error": None},
            provides=["git"],
            requires=["ci"],
        )
    ]
    rig.api.secrets = {"api_token": True, "admin_password": False}
    assert rig.go("status", "forgejo") == 0
    text = rig.said
    assert "Forgejo 1.0.0 (forgejo)" in text and "forgejo in English" in text
    assert "Flavour: cpu" in text and "Provides: git" in text and "Needs: ci" in text
    assert "api_token (set)" in text and "admin_password (not set)" in text


def test_status_of_an_unknown_module() -> None:
    rig = Rig()
    assert rig.go("status", "nope") == 1
    assert "no module called “nope”" in rig.warned


def test_status_reports_a_failed_module_in_words() -> None:
    rig = Rig()
    rig.api.modules = [entry("x", {"state": "failed", "error": "down_failed"})]
    rig.go("status", "x")
    assert "failed" in rig.said and "could not be stopped" in rig.said


# --- install and uninstall ----------------------------------------------------------------------


def test_install_asks_first_and_does_nothing_when_declined() -> None:
    rig = Rig(answers=["n"])
    rig.api.plans = [plan(("install", "forgejo"))]
    assert rig.go("install", "forgejo") == 1
    assert rig.api.started == []
    assert "Nothing was changed" in rig.said and rig.asked == ["Go ahead? [y/N] "]


@pytest.mark.parametrize("answer", ["y", "Y", "yes", "o", "oui"])
def test_install_goes_ahead_on_yes_and_follows_the_operation(answer: str) -> None:
    rig = Rig(answers=[answer])
    rig.api.plans = [
        plan(("install", "forgejo"), ("install", "woodpecker"), auto_added=["forgejo"])
    ]
    rig.api.operations = [RUNNING, RUNNING, DONE]
    assert rig.go("install", "woodpecker") == 0
    assert rig.api.started and rig.api.started[0]["modules"] == ["woodpecker"]
    assert (
        "install forgejo" in rig.said
        and "Also installed because they are needed: forgejo" in rig.said
    )
    assert rig.said.rstrip().endswith("Done.") and len(rig.sleeps) == 2


def test_no_answer_at_all_is_a_no() -> None:
    rig = Rig(answers=[])  # stdin closed
    rig.api.plans = [plan(("install", "forgejo"))]
    assert rig.go("install", "forgejo") == 1
    assert rig.api.started == []


def test_yes_skips_the_question() -> None:
    rig = Rig()
    rig.api.plans = [plan(("install", "forgejo"))]
    rig.api.operations = [DONE]
    assert rig.go("install", "forgejo", "--yes") == 0
    assert rig.asked == [] and rig.api.started


def test_a_failed_operation_says_where_why_and_what_was_undone() -> None:
    rig = Rig()
    rig.api.plans = [plan(("install", "woodpecker"))]
    rig.api.operations = [
        {
            "state": "failed",
            "error": {
                "module": "woodpecker",
                "step": "up",
                "code": "up_failed",
                "rolled_back": ["woodpecker"],
                "partial": True,
            },
        }
    ]
    assert rig.go("install", "woodpecker", "--yes") == 1
    assert "Failed at “woodpecker”, step “up”: the module could not be started." in rig.warned
    assert (
        "Rolled back: woodpecker" in rig.warned and "removals had already been done" in rig.warned
    )


def test_a_failure_in_french() -> None:
    rig = Rig(lang="fr")
    rig.api.plans = [plan(("install", "x"))]
    rig.api.operations = [
        {"state": "failed", "error": {"module": "x", "step": "health", "code": "unhealthy"}}
    ]
    rig.go("install", "x", "--yes")
    assert "Échec sur « x », étape « health »" in rig.warned and "pas devenu sain" in rig.warned


def test_an_unknown_failure_code_is_shown_not_hidden() -> None:
    rig = Rig()
    rig.api.plans = [plan(("install", "x"))]
    rig.api.operations = [
        {"state": "failed", "error": {"module": "x", "step": "s", "code": "brand_new"}}
    ]
    rig.go("install", "x", "--yes")
    assert "brand_new" in rig.warned


def test_a_choice_is_asked_for_then_given() -> None:
    rig = Rig()
    rig.api.plans = [
        rejected("module_needs_choice", capability="git", candidates=["forgejo", "gitea"])
    ]
    assert rig.go("install", "woodpecker", "--yes") == 1
    assert "Several modules can provide “git” (forgejo, gitea)" in rig.warned
    assert "--choose git=<module>" in rig.warned and rig.api.started == []
    rig2 = Rig()
    rig2.api.plans = [plan(("install", "forgejo"), ("install", "woodpecker"))]
    rig2.api.operations = [DONE]
    assert rig2.go("install", "woodpecker", "--choose", "git=forgejo", "--yes") == 0
    assert rig2.api.bodies[0]["choices"] == {"git": "forgejo"}


def test_a_malformed_choice_is_a_usage_error() -> None:
    rig = Rig()
    assert rig.go("install", "x", "--choose", "git") == 2
    assert rig.api.bodies == []


def test_replace_is_passed_on() -> None:
    rig = Rig()
    rig.api.plans = [plan(("uninstall", "forgejo"), ("install", "gitea"))]
    rig.api.operations = [DONE]
    rig.go("install", "gitea", "--replace", "--yes")
    assert rig.api.bodies[0]["replace"] is True


def test_removing_a_module_others_need_asks_about_the_cascade_separately() -> None:
    rig = Rig(answers=["n"])
    rig.api.plans = [rejected("module_needs_confirmation", cascade=["woodpecker"])]
    assert rig.go("uninstall", "forgejo") == 1
    assert "also removes the modules that depend on it: woodpecker" in rig.warned
    assert rig.asked == ["Remove them too? [y/N] "] and rig.api.started == []
    # accepted: the plan is asked again with the confirmation, then the usual question
    ok = Rig(answers=["y", "y"])
    ok.api.plans = [
        rejected("module_needs_confirmation", cascade=["woodpecker"]),
        plan(("uninstall", "woodpecker"), ("uninstall", "forgejo")),
    ]
    ok.api.operations = [DONE]
    assert ok.go("uninstall", "forgejo") == 0
    assert [b["confirm_cascade"] for b in ok.api.bodies] == [False, True]
    assert ok.api.started[0]["confirm_cascade"] is True


def test_yes_confirms_a_cascade_too() -> None:
    rig = Rig()
    rig.api.plans = [
        rejected("module_needs_confirmation", cascade=["woodpecker"]),
        plan(("uninstall", "woodpecker"), ("uninstall", "forgejo")),
    ]
    rig.api.operations = [DONE]
    assert rig.go("uninstall", "forgejo", "--yes") == 0
    assert rig.asked == [] and rig.api.started[0]["confirm_cascade"] is True


def test_nothing_to_do_is_said_and_nothing_is_started() -> None:
    rig = Rig()
    rig.api.plans = [plan()]
    assert rig.go("install", "forgejo", "--yes") == 0
    assert "Nothing to do" in rig.said and rig.api.started == []


@pytest.mark.parametrize(
    ("code", "status", "fragment"),
    [
        ("module_unknown", 404, "no module called “zzz”"),
        ("module_busy", 409, "Another module operation is running"),
        ("module_conflict", 409, "Only one module can provide “git”"),
        ("module_unsatisfiable", 422, "needs “git”"),
        ("module_no_compatible_variant", 422, "does not fit this machine (ram_mb: needs 9, has 1)"),
        ("something_new", 418, "refused the request (something_new)"),
    ],
)
def test_planning_refusals_are_explained(code: str, status: int, fragment: str) -> None:
    rig = Rig()
    rig.api.plans = [
        rejected(
            code,
            status,
            module="zzz",
            capability="git",
            modules=["a", "b"],
            problems=[{"code": "ram_mb", "needed": 9, "have": 1}],
        )
    ]
    assert rig.go("install", "zzz", "--yes") == 1
    assert fragment in rig.warned


def test_a_busy_manager_at_start_is_a_refusal() -> None:
    rig = Rig()
    rig.api.plans = [plan(("install", "forgejo"))]
    rig.api.start_error = rejected("module_busy")
    assert rig.go("install", "forgejo", "--yes") == 1
    assert "Another module operation is running" in rig.warned


def test_an_unreachable_manager_has_its_own_exit_code_everywhere() -> None:
    for argv in (["list"], ["status", "x"], ["install", "x", "--yes"], ["uninstall", "x", "--yes"]):
        rig = Rig()
        rig.api.down = True
        assert rig.go(*argv) == EXIT_UNAVAILABLE
        assert "not running or does not answer" in rig.warned


def test_an_operation_that_never_ends_is_left_running_not_waited_for_forever() -> None:
    rig = Rig()
    rig.api.plans = [plan(("install", "x"))]
    rig.api.operations = [RUNNING]
    assert rig.go("install", "x", "--yes") == 1
    assert rig.now > PATIENCE_S and "Still running after an hour (operation op1)" in rig.warned


def test_nothing_secret_is_ever_asked_for_or_printed() -> None:
    api = FakeAPI()
    assert not hasattr(api, "connections")  # the CLI cannot reach the endpoint that has values
    rig = Rig()
    rig.api.modules = [entry("forgejo", {"state": "running"})]
    rig.api.secrets = {"api_token": True}
    rig.go("status", "forgejo")
    assert "token-value" not in rig.said + rig.warned


# --- through the real entry point ---------------------------------------------------------------


def test_the_command_is_wired_into_cobble_cli(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = FakeAPI()
    fake.modules = [entry("forgejo", {"state": "running"})]
    monkeypatch.setattr(
        "cobble.cli_modules.HttpModuleManager.from_settings", classmethod(lambda cls, s: fake)
    )
    assert cli.main(["modules", "list"]) == 0
    assert "forgejo" in capsys.readouterr().out


# --- translations are complete ------------------------------------------------------------------


def _catalog(lang: str) -> dict[str, str]:
    from cobble.i18n import _catalog as load

    return load(lang)


def test_every_error_code_the_ui_knows_is_known_to_the_cli_in_both_languages() -> None:
    ui = json.loads((ROOT / "ui/src/locales/en/errors.json").read_text("utf-8"))
    step_codes = {k.removeprefix("module_code_") for k in ui if k.startswith("module_code_")}
    refusals = {k for k in ui if k.startswith("module_") and not k.startswith("module_code_")}
    for lang in ("en", "fr"):
        catalog = _catalog(lang)
        missing = [c for c in step_codes if f"cli.modules.code.{c}" not in catalog]
        assert not missing, (lang, missing)
        known = {
            k.removeprefix("cli.modules.refused.")
            for k in catalog
            if k.startswith("cli.modules.refused.")
        }
        absent = sorted(r for r in refusals - known if r not in {"module_manager_unavailable"})
        assert not absent, (lang, absent)


def test_placeholders_match_between_languages() -> None:
    en, fr = _catalog("en"), _catalog("fr")
    keys = [k for k in en if k.startswith("cli.modules.")]
    assert set(keys) == {k for k in fr if k.startswith("cli.modules.")}
    for key in keys:
        assert set(re.findall(r"{(\w+)}", en[key])) == set(re.findall(r"{(\w+)}", fr[key])), key


def test_a_removal_does_not_talk_about_downloads() -> None:
    rig = Rig()
    rig.api.plans = [plan(("uninstall", "x"))]
    rig.api.operations = [DONE]
    rig.go("uninstall", "x", "--yes")
    assert "download" not in rig.said
    install = Rig()
    install.api.plans = [plan(("install", "x"))]
    install.api.operations = [DONE]
    install.go("install", "x", "--yes")
    assert "downloaded" in install.said


# --- starter packs ------------------------------------------------------------------------------


def pack(pack_id: str, modules: list[str], *, fits: bool = True, **over: Any) -> dict[str, Any]:
    return {
        "id": pack_id,
        "name": {"en": f"{pack_id} name", "fr": f"{pack_id} nom"},
        "description": {"en": f"{pack_id} in English", "fr": f"{pack_id} en français"},
        "modules": modules,
        "fit": {
            "ok": fits,
            "problems": []
            if fits
            else [
                {"module": None, "code": "gpu", "needed": "any", "have": "none"},
                {"module": "ollama", "code": "ram", "needed": "4096", "have": "2048"},
            ],
        },
        "recommended": False,
        "installed": False,
        **over,
    }


def test_packs_are_listed_with_their_fit_and_what_is_proposed() -> None:
    rig = Rig()
    rig.api.pack_body = {
        "packs": [
            pack("local-cpu", ["forgejo", "ollama"], recommended=True),
            pack("local-gpu", ["forgejo", "ollama"], fits=False),
            pack("api-only", ["forgejo"], installed=True),
        ],
        "problems": {},
        "recommended": "local-cpu",
    }
    assert rig.go("packs") == 0
    text = rig.said
    assert (
        "local-cpu name  [recommended for this machine, not installed]  fits this machine" in text
    )
    assert (
        "does not fit this machine (gpu: needs any, has none; ollama: ram: needs 4096, has 2048)"
        in text
    )
    assert "[installed]" in text and "modules: forgejo, ollama" in text
    assert "local-cpu in English" in text


def test_packs_in_french_and_when_there_are_none() -> None:
    rig = Rig(lang="fr")
    rig.api.pack_body = {"packs": [pack("p", ["forgejo"], recommended=True)], "problems": {}}
    rig.go("packs")
    assert "p nom" in rig.said and "recommandé pour cette machine" in rig.said
    assert "p en français" in rig.said
    empty = Rig()
    empty.go("packs")
    assert "no starter pack" in empty.said


def test_a_pack_that_cannot_be_used_is_reported_not_hidden() -> None:
    rig = Rig()
    rig.api.pack_body = {"packs": [], "problems": {"ghosts": ["unknown module: ghost"]}}
    rig.go("packs")
    assert "“ghosts” is not usable" in rig.warned and "unknown module: ghost" in rig.warned


def test_installing_a_pack_installs_all_its_modules_in_one_operation() -> None:
    rig = Rig()
    rig.api.pack_body = {"packs": [pack("api-only", ["forgejo", "woodpecker"])], "problems": {}}
    rig.api.plans = [plan(("install", "forgejo"), ("install", "woodpecker"))]
    rig.api.operations = [DONE]
    assert rig.go("install", "--pack", "api-only", "--yes") == 0
    assert rig.api.bodies[0]["modules"] == ["forgejo", "woodpecker"]
    assert rig.api.started[0]["modules"] == ["forgejo", "woodpecker"]


def test_modules_named_next_to_a_pack_are_added_once() -> None:
    rig = Rig()
    rig.api.pack_body = {"packs": [pack("p", ["forgejo", "woodpecker"])], "problems": {}}
    rig.api.plans = [plan(("install", "forgejo"))]
    rig.api.operations = [DONE]
    rig.go("install", "forgejo", "extra", "--pack", "p", "--yes")
    assert rig.api.bodies[0]["modules"] == ["forgejo", "woodpecker", "extra"]


def test_a_pack_that_does_not_fit_is_refused_with_the_reasons_and_nothing_is_planned() -> None:
    rig = Rig()
    rig.api.pack_body = {"packs": [pack("local-gpu", ["ollama"], fits=False)], "problems": {}}
    assert rig.go("install", "--pack", "local-gpu", "--yes") == 1
    assert "does not fit this machine" in rig.warned and "gpu: needs any, has none" in rig.warned
    assert rig.api.bodies == [] and rig.api.started == []


def test_an_unknown_pack_is_named() -> None:
    rig = Rig()
    assert rig.go("install", "--pack", "nope", "--yes") == 1
    assert "no starter pack called “nope”" in rig.warned


def test_install_needs_a_module_or_a_pack() -> None:
    rig = Rig()
    assert rig.go("install", "--yes") == 2
    assert "Name at least one module" in rig.warned
    assert rig.api.bodies == []


def test_uninstall_still_needs_a_module() -> None:
    with pytest.raises(SystemExit):
        Rig().go("uninstall", "--yes")


def test_an_unreachable_manager_is_reported_for_packs_too() -> None:
    for argv in (["packs"], ["install", "--pack", "p", "--yes"]):
        rig = Rig()
        rig.api.down = True
        assert rig.go(*argv) == EXIT_UNAVAILABLE
