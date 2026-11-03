"""Model presets: ready-made role routes, filled in with the models the owner picks.

A preset is a template over three slots, not a list of model names (the platform has no price
or quality table yet, so it cannot tell which connected model is the strong one):

- `local`: a model served on this machine (free; the first one by default),
- `cheap`: an inexpensive model for the high-volume roles,
- `strong`: the model for the roles where quality counts most (the platform default by default).

Applying a preset replaces the routes of all five roles. Everything here is pure: no database,
no network, so every combination can be tested.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from cobble.capabilities.llm import Role

from .policy import MAX_CHAIN, ROLES

SLOTS = ("local", "cheap", "strong")


@dataclass(frozen=True)
class Preset:
    id: str
    # role -> slots to try, best first
    chains: Mapping[Role, tuple[str, ...]]
    # slots the preset cannot work without; the others are skipped when empty
    required: tuple[str, ...]


PRESETS: tuple[Preset, ...] = (
    # Cheapest: the volume work runs on this machine, the paid models only plan, review the
    # escalations and catch what the local model cannot answer.
    Preset(
        "economical-local",
        {
            Role.PLANNER: ("strong", "cheap"),
            Role.TEST_WRITER: ("local", "cheap"),
            Role.WORKER: ("local", "cheap"),
            Role.REVIEWER: ("local", "cheap"),
            Role.ESCALATION: ("strong",),
        },
        required=("local", "strong"),
    ),
    # Balanced: an inexpensive model writes tests and code, the strong one plans and reviews.
    Preset(
        "balanced",
        {
            Role.PLANNER: ("strong",),
            Role.TEST_WRITER: ("cheap", "strong"),
            Role.WORKER: ("cheap", "strong"),
            Role.REVIEWER: ("strong",),
            Role.ESCALATION: ("strong",),
        },
        required=("strong",),
    ),
)

BY_ID = {preset.id: preset for preset in PRESETS}


@dataclass(frozen=True)
class Outcome:
    """What a preset gives for some slot choices."""

    missing: tuple[str, ...]  # required slots with no model: the preset cannot be applied
    routes: dict[str, list[str]]  # role -> chain (empty when `missing`)

    @property
    def available(self) -> bool:
        return not self.missing


def resolve(preset: Preset, slots: Mapping[str, str | None]) -> Outcome:
    """Fill the preset's roles from `slots` (slot -> model name or None).

    A `cheap` slot left empty falls back to `strong`: a preset never has holes, and a chain
    never repeats a model or exceeds `MAX_CHAIN`."""
    chosen = {slot: slots.get(slot) or None for slot in SLOTS}
    if chosen["cheap"] is None:
        chosen["cheap"] = chosen["strong"]
    missing = tuple(slot for slot in preset.required if chosen[slot] is None)
    if missing:
        return Outcome(missing, {})
    routes: dict[str, list[str]] = {}
    for role in ROLES:
        models = [chosen[slot] for slot in preset.chains[role] if chosen[slot] is not None]
        chain = list(dict.fromkeys(m for m in models if m is not None))[:MAX_CHAIN]
        if chain:
            routes[role.value] = chain
    return Outcome((), routes)
