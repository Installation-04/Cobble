"""Property tests: the v0.2 criterion ("install and uninstall in any order") in test form."""

from __future__ import annotations

from typing import Any

from hypothesis import given, settings
from hypothesis import strategies as st

from cobble_sdk import Manifest, ResolveError, desired_links, plan_install, plan_uninstall, resolve
from cobble_sdk.resolve import providers_of

from .catalogs import mod

CAPS = ["c0", "c1", "c2", "c3"]
PROFILE = settings(max_examples=150, deadline=None, derandomize=True)


@st.composite
def catalogs(draw: st.DrawFn) -> dict[str, Manifest]:
    """Acyclic by construction: a module only requires capabilities lower than all it provides."""
    count = draw(st.integers(min_value=3, max_value=7))
    result: dict[str, Manifest] = {}
    for index in range(count):
        provides = sorted(draw(st.sets(st.sampled_from(CAPS), max_size=2)))
        lowest = min((CAPS.index(c) for c in provides), default=len(CAPS))
        pool = CAPS[:lowest]
        requires = sorted(draw(st.sets(st.sampled_from(pool), max_size=2))) if pool else []
        exclusive = sorted(draw(st.sets(st.sampled_from(provides)))) if provides else []
        module_id = f"m{index}"
        result[module_id] = mod(
            module_id, provides=provides, requires=requires, exclusive=exclusive
        )
    return result


@st.composite
def scenarios(draw: st.DrawFn) -> tuple[dict[str, Manifest], dict[str, str], list[tuple[str, str]]]:
    cat = draw(catalogs())
    choices = {}
    for capability in CAPS:
        candidates = providers_of(cat, capability)
        if len(candidates) > 1:
            choices[capability] = draw(st.sampled_from(candidates))
    ops = draw(
        st.lists(
            st.tuples(
                st.sampled_from(["install", "replace", "uninstall"]),
                st.sampled_from(sorted(cat)),
            ),
            max_size=12,
        )
    )
    return cat, choices, ops


def _step(
    cat: dict[str, Manifest],
    explicit: frozenset[str],
    choices: dict[str, str],
    op: str,
    module: str,
) -> Any:
    if op == "uninstall":
        return plan_uninstall(cat, explicit, [module], choices, confirm_cascade=True)
    return plan_install(cat, explicit, [module], choices, replace=op == "replace")


def _assert_closed(cat: dict[str, Manifest], installed: frozenset[str]) -> None:
    provided = {p.capability for m in installed for p in cat[m].provides}
    for module in installed:
        assert set(cat[module].requires) <= provided, f"{module} has a missing requirement"
        for capability in cat[module].exclusive:
            providers = [
                m for m in installed if capability in {p.capability for p in cat[m].provides}
            ]
            assert providers == [module], f"{capability} has several providers"


def _assert_providers_first(
    cat: dict[str, Manifest], world: frozenset[str], order: list[str]
) -> None:
    """Independent of `install_order`: a module never precedes a provider it depends on."""
    position = {module: index for index, module in enumerate(order)}
    for module in order:
        for capability in cat[module].requires:
            for provider in order:
                if provider != module and capability in {
                    p.capability for p in cat[provider].provides
                }:
                    assert position[provider] < position[module], f"{module} before {provider}"
    assert set(order) <= world


@PROFILE
@given(scenarios())
def test_invariants_hold_after_every_operation(
    scenario: tuple[dict[str, Manifest], dict[str, str], list[tuple[str, str]]],
) -> None:
    cat, choices, ops = scenario
    explicit: frozenset[str] = frozenset()
    for op, module in ops:
        try:
            plan = _step(cat, explicit, choices, op, module)
        except ResolveError:
            continue  # a refused operation changes nothing (the state is immutable data)
        resolution = resolve(cat, plan.explicit, choices)
        assert plan.installed == resolution.installed
        assert plan.explicit <= plan.installed
        _assert_closed(cat, plan.installed)
        assert desired_links(cat, plan.installed) == resolution.links
        explicit = plan.explicit


@PROFILE
@given(scenarios())
def test_plan_steps_turn_the_old_state_into_the_new_one_in_a_valid_order(
    scenario: tuple[dict[str, Manifest], dict[str, str], list[tuple[str, str]]],
) -> None:
    cat, choices, ops = scenario
    explicit: frozenset[str] = frozenset()
    for op, module in ops:
        try:
            plan = _step(cat, explicit, choices, op, module)
        except ResolveError:
            continue
        old = resolve(cat, explicit, choices).installed
        live = set(old)
        for step in plan.steps:
            if step.action == "install":
                assert step.module not in live
                live.add(step.module)
            else:
                assert step.module in live
                live.discard(step.module)
        assert frozenset(live) == plan.installed
        _assert_providers_first(
            cat, plan.installed, [s.module for s in plan.steps if s.action == "install"]
        )
        uninstalls = [s.module for s in plan.steps if s.action == "uninstall"]
        _assert_providers_first(cat, old, list(reversed(uninstalls)))
        # uninstalls come before installs
        actions = [s.action for s in plan.steps]
        assert actions == sorted(actions, key=lambda a: a == "install")
        explicit = plan.explicit


@PROFILE
@given(scenarios())
def test_same_explicit_set_means_same_state_whatever_the_history(
    scenario: tuple[dict[str, Manifest], dict[str, str], list[tuple[str, str]]],
) -> None:
    cat, choices, ops = scenario
    explicit: frozenset[str] = frozenset()
    history: dict[frozenset[str], Any] = {}
    for op, module in ops:
        try:
            plan = _step(cat, explicit, choices, op, module)
        except ResolveError:
            continue
        explicit = plan.explicit
        state = (plan.installed, desired_links(cat, plan.installed))
        assert history.setdefault(explicit, state) == state


@PROFILE
@given(scenarios())
def test_uninstalling_everything_leaves_nothing(
    scenario: tuple[dict[str, Manifest], dict[str, str], list[tuple[str, str]]],
) -> None:
    cat, choices, ops = scenario
    explicit: frozenset[str] = frozenset()
    for op, module in ops:
        try:
            explicit = _step(cat, explicit, choices, op, module).explicit
        except ResolveError:
            continue
    for module in sorted(explicit):
        if module in resolve(cat, explicit, choices).installed and module in explicit:
            explicit = plan_uninstall(
                cat, explicit, [module], choices, confirm_cascade=True
            ).explicit
    assert explicit == frozenset()
    assert resolve(cat, explicit, choices).installed == frozenset()


@PROFILE
@given(scenarios(), st.data())
def test_install_then_uninstall_restores_the_previous_state(
    scenario: tuple[dict[str, Manifest], dict[str, str], list[tuple[str, str]]], data: st.DataObject
) -> None:
    cat, choices, ops = scenario
    explicit: frozenset[str] = frozenset()
    for op, module in ops:
        try:
            explicit = _step(cat, explicit, choices, op, module).explicit
        except ResolveError:
            continue
    installed = resolve(cat, explicit, choices).installed
    candidates = sorted(set(cat) - installed)
    if not candidates:
        return
    module = data.draw(st.sampled_from(candidates))
    try:
        plan = plan_install(cat, explicit, [module], choices)
    except ResolveError:
        return
    if plan.auto_removed or plan.replaced:
        return  # installing it made other modules unnecessary: not a pure round trip
    back = plan_uninstall(cat, plan.explicit, [module], choices)
    assert back.explicit == explicit
    assert back.installed == installed


@PROFILE
@given(scenarios(), st.randoms())
def test_resolution_does_not_depend_on_dictionary_order(
    scenario: tuple[dict[str, Manifest], dict[str, str], list[tuple[str, str]]], rnd: Any
) -> None:
    cat, choices, ops = scenario
    explicit = frozenset(m for _, m in ops)
    shuffled_keys = sorted(cat)
    rnd.shuffle(shuffled_keys)
    shuffled = {key: cat[key] for key in shuffled_keys}
    try:
        expected = resolve(cat, explicit, choices)
    except ResolveError as exc:
        try:
            resolve(shuffled, explicit, choices)
        except ResolveError as other:
            assert type(other) is type(exc)
            return
        raise AssertionError("only one ordering failed") from None
    assert resolve(shuffled, explicit, choices) == expected
