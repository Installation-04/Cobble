"""v0.2 acceptance: every official module installs and uninstalls in any order, without conflict.

Runs the real module-manager (database, vault, hooks order, links) with a fake Docker against the
manifests of the shipped catalogue, over every order of installs and of removals, and checks after
each step that the installed set, the running projects and the links are exactly what the
explicitly requested modules call for, and that nothing is left once everything is removed.
"""

from __future__ import annotations

import itertools
from pathlib import Path

import pytest
from cobble_sdk import Hardware, Manifest, NotInstalled, load_manifest, plan_uninstall, resolve
from sqlalchemy import select

from cobble.db.models import ModuleLink

from .test_module_manager import Rig

CATALOG = Path(__file__).resolve().parents[3] / "catalog"


def official() -> dict[str, Manifest]:
    return {p.parent.name: load_manifest(p) for p in sorted(CATALOG.glob("*/manifest.yaml"))}


MODULES = official()
IDS = sorted(MODULES)


def composes() -> dict[str, dict[str, object]]:
    """A compose file with every service each manifest declares (the shape the rules check; the
    real files are rendered by Docker and are linted by `cobble-sdk lint`)."""
    out: dict[str, dict[str, object]] = {}
    for module_id, m in MODULES.items():
        names = set(m.bus)
        if m.web_ui:
            names.add(m.web_ui.service)
        if m.llm:
            names.add(m.llm.service)
        out[module_id] = {
            "services": {n: {"image": m.images[0]} for n in sorted(names) or [module_id]}
        }
    return out


def rig(hardware: Hardware | None = None) -> Rig:
    r = Rig(list(MODULES.values()), hardware or Hardware(ram_mb=16384))
    r.catalog.composes = composes()  # type: ignore[assignment]
    return r


def check(r: Rig, explicit: set[str]) -> None:
    """The system is exactly what `explicit` calls for, whatever path led here."""
    wanted = resolve(MODULES, explicit)
    assert set(r.modules()) == set(wanted.installed)
    assert set(r.runner.running) == {f"cobble-{m}" for m in wanted.installed}
    with r.sessions() as s:
        links = {
            (row.consumer, row.provider, row.capability) for row in s.scalars(select(ModuleLink))
        }
    assert links == {(link.consumer, link.provider, link.capability) for link in wanted.links}


def test_the_catalogue_is_the_expected_one() -> None:
    assert IDS == ["aider", "forgejo", "ollama", "preview", "woodpecker"]


def run_story(install: tuple[str, ...], removal: tuple[str, ...]) -> None:
    r = rig()
    explicit: set[str] = set()
    for module in install:
        r.manager.install([module])
        explicit.add(module)
        check(r, explicit)
    for module in removal:
        # Removing forgejo while woodpecker needs it takes woodpecker with it: that is the
        # confirmed cascade, and what it removes is exactly what lost its provider.
        if module not in resolve(MODULES, explicit).installed:
            with pytest.raises(NotInstalled):  # already taken away by an earlier cascade
                r.manager.uninstall([module], confirm_cascade=True)
            continue
        r.manager.uninstall([module], confirm_cascade=True)
        explicit = set(plan_uninstall(MODULES, explicit, [module], confirm_cascade=True).explicit)
        check(r, explicit)
    assert r.counts() == {"modules": 0, "secrets": 0, "links": 0}
    assert r.runner.running == {} and r.runner.volumes == set()


@pytest.mark.parametrize("order", list(itertools.permutations(IDS)))
def test_installing_one_by_one_in_any_order_then_removing_in_the_same_reversed_or_rotated_order(
    order: tuple[str, ...],
) -> None:
    for removal in (order, order[::-1], order[2:] + order[:2]):
        run_story(order, removal)


@pytest.mark.parametrize("removal", list(itertools.permutations(IDS)))
def test_removing_in_any_order_after_a_fixed_install(removal: tuple[str, ...]) -> None:
    run_story(tuple(IDS), removal)


def test_installing_everything_at_once_gives_the_same_state() -> None:
    r = rig()
    r.manager.install(IDS)
    check(r, set(IDS))
    r2 = rig()
    for module in reversed(IDS):
        r2.manager.install([module])
    assert set(r.modules()) == set(r2.modules())


def test_forgejo_and_woodpecker_plug_themselves_together() -> None:
    r = rig()
    r.manager.install(["woodpecker"])  # asks for no git module: forgejo is the only provider
    assert set(r.modules()) == {"forgejo", "woodpecker"}
    with r.sessions() as s:
        links = {(x.consumer, x.provider, x.capability) for x in s.scalars(select(ModuleLink))}
    assert links == {("woodpecker", "forgejo", "git")}


def test_ollama_is_offered_to_the_gateway_on_its_own() -> None:
    r = rig()
    r.manager.install(["ollama"])
    assert "llm-backend" in {p.capability for p in MODULES["ollama"].provides}
    assert set(r.modules()) == {"ollama"}


def test_a_machine_too_small_for_a_module_refuses_it_and_leaves_nothing_behind() -> None:
    r = rig(Hardware(ram_mb=512))
    heavy = [
        m
        for m in IDS
        if MODULES[m].hardware.min_ram_mb > 512
        or any(v.min_ram_mb > 512 for v in MODULES[m].variants)
    ]
    for module in heavy:
        with pytest.raises(Exception):  # noqa: B017 - the manager's refusal type depends on the step
            r.manager.install([module])
        assert r.counts() == {"modules": 0, "secrets": 0, "links": 0}
        assert r.runner.running == {}
