"""Presets are pure: every combination of slots can be checked."""

from __future__ import annotations

import itertools

import pytest

from cobble.router.policy import MAX_CHAIN, ROLES
from cobble.router.presets import BY_ID, PRESETS, SLOTS, resolve

ROLE_NAMES = [r.value for r in ROLES]


def test_there_are_the_two_presets_of_the_plan() -> None:
    assert [p.id for p in PRESETS] == ["economical-local", "balanced"]
    for preset in PRESETS:
        assert set(preset.chains) == set(ROLES)  # every role is covered, none forgotten
        assert set(preset.required) <= set(SLOTS)


def test_economical_local_keeps_the_volume_work_on_this_machine() -> None:
    out = resolve(BY_ID["economical-local"], {"local": "coder", "cheap": "mini", "strong": "big"})
    assert out.available
    assert out.routes == {
        "planner": ["big", "mini"],
        "test-writer": ["coder", "mini"],
        "worker": ["coder", "mini"],
        "reviewer": ["coder", "mini"],
        "escalation": ["big"],
    }


def test_balanced_uses_the_cheap_model_for_volume_and_the_strong_one_for_judgement() -> None:
    out = resolve(BY_ID["balanced"], {"cheap": "mini", "strong": "big"})
    assert out.routes == {
        "planner": ["big"],
        "test-writer": ["mini", "big"],
        "worker": ["mini", "big"],
        "reviewer": ["big"],
        "escalation": ["big"],
    }


@pytest.mark.parametrize("preset", PRESETS, ids=lambda p: p.id)
def test_a_missing_required_slot_makes_the_preset_unavailable_and_changes_nothing(preset) -> None:  # type: ignore[no-untyped-def]
    for required in preset.required:
        slots = {"local": "a", "cheap": "b", "strong": "c"}
        slots[required] = None  # type: ignore[assignment]
        out = resolve(preset, slots)
        assert not out.available and out.missing == (required,) and out.routes == {}


def test_an_empty_cheap_slot_falls_back_to_the_strong_model() -> None:
    out = resolve(BY_ID["balanced"], {"strong": "big"})
    assert out.routes["worker"] == ["big"]  # no duplicate, no hole
    eco = resolve(BY_ID["economical-local"], {"local": "coder", "strong": "big"})
    assert eco.routes["worker"] == ["coder", "big"] and eco.routes["planner"] == ["big"]


def test_empty_strings_count_as_empty() -> None:
    assert not resolve(BY_ID["balanced"], {"strong": ""}).available


@pytest.mark.parametrize("preset", PRESETS, ids=lambda p: p.id)
def test_whatever_the_choices_a_result_is_complete_deduplicated_and_short(preset) -> None:  # type: ignore[no-untyped-def]
    models = [None, "x", "y"]
    for local, cheap, strong in itertools.product(models, repeat=3):
        out = resolve(preset, {"local": local, "cheap": cheap, "strong": strong})
        if not out.available:
            assert out.routes == {}
            continue
        assert set(out.routes) == set(ROLE_NAMES)  # all five roles get a route
        for chain in out.routes.values():
            assert chain and len(chain) == len(set(chain)) and len(chain) <= MAX_CHAIN
            assert None not in chain
