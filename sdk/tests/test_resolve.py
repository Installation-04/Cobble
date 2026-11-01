from __future__ import annotations

import itertools

import pytest

from cobble_sdk import (
    Conflict,
    DependencyCycle,
    Hardware,
    Link,
    NeedsChoice,
    NeedsConfirmation,
    NoCompatibleVariant,
    NotInstalled,
    Step,
    UnknownModule,
    Unsatisfiable,
    choose_variant,
    desired_links,
    plan_install,
    plan_uninstall,
    resolve,
)
from cobble_sdk.resolve import InvalidChoice, check_hardware

from .catalogs import catalog, mod, real_shaped


def test_a_requirement_is_satisfied_automatically_by_the_only_provider() -> None:
    cat = real_shaped()
    plan = plan_install(cat, set(), ["woodpecker"], {"git": "forgejo"})
    assert plan.steps == (Step("install", "forgejo"), Step("install", "woodpecker"))
    assert plan.auto_added == ("forgejo",)
    assert plan.explicit == {"woodpecker"}
    assert plan.links_added == {Link("woodpecker", "forgejo", "git")}


def test_with_several_candidates_the_caller_must_choose() -> None:
    cat = real_shaped()
    with pytest.raises(NeedsChoice) as info:
        plan_install(cat, set(), ["woodpecker"])
    assert info.value.capability == "git"
    assert info.value.candidates == ("forgejo", "gitea")  # sorted: deterministic
    chosen = plan_install(cat, set(), ["woodpecker"], {"git": "gitea"})
    assert Step("install", "gitea") in chosen.steps
    with pytest.raises(InvalidChoice):
        plan_install(cat, set(), ["woodpecker"], {"git": "litellm"})


def test_an_explicit_provider_satisfies_the_requirement_so_nothing_else_is_added() -> None:
    cat = real_shaped()
    plan = plan_install(cat, {"gitea"}, ["woodpecker"])  # no choice needed: gitea is installed
    assert plan.steps == (Step("install", "woodpecker"),)
    assert plan.auto_added == ()


def test_a_requirement_nobody_provides_is_unsatisfiable() -> None:
    cat = catalog(mod("lonely", requires=["nothing"]))
    with pytest.raises(Unsatisfiable) as info:
        resolve(cat, {"lonely"})
    assert (info.value.module, info.value.capability) == ("lonely", "nothing")


def test_unknown_modules_are_rejected() -> None:
    cat = real_shaped()
    with pytest.raises(UnknownModule):
        plan_install(cat, set(), ["nope"])
    with pytest.raises(UnknownModule):
        resolve(cat, {"nope"})


def test_two_providers_of_an_exclusive_capability_conflict() -> None:
    cat = real_shaped()
    with pytest.raises(Conflict) as info:
        plan_install(cat, {"forgejo"}, ["gitea"])
    assert info.value.capability == "git"
    assert info.value.modules == ("forgejo", "gitea")


def test_replace_swaps_the_conflicting_module_and_relinks_dependents() -> None:
    cat = real_shaped()
    plan = plan_install(cat, {"forgejo", "woodpecker"}, ["gitea"], replace=True)
    assert plan.replaced == ("forgejo",)
    assert plan.explicit == {"gitea", "woodpecker"}
    assert plan.steps == (Step("uninstall", "forgejo"), Step("install", "gitea"))
    assert plan.links_removed == {Link("woodpecker", "forgejo", "git")}
    assert plan.links_added == {Link("woodpecker", "gitea", "git")}


def test_uninstalling_the_last_consumer_drops_the_dependency_it_pulled_in() -> None:
    cat = real_shaped()
    explicit = {"woodpecker"}
    plan = plan_uninstall(cat, explicit, ["woodpecker"], {"git": "forgejo"})
    assert plan.explicit == frozenset()
    assert plan.auto_removed == ("forgejo",)
    assert plan.steps == (Step("uninstall", "woodpecker"), Step("uninstall", "forgejo"))


def test_uninstalling_a_provider_asks_to_confirm_the_cascade() -> None:
    cat = real_shaped()
    explicit = {"forgejo", "woodpecker"}
    with pytest.raises(NeedsConfirmation) as info:
        plan_uninstall(cat, explicit, ["forgejo"])
    assert info.value.cascade == ("woodpecker",)
    plan = plan_uninstall(cat, explicit, ["forgejo"], confirm_cascade=True)
    assert plan.cascade == ("woodpecker",)
    assert plan.explicit == frozenset()
    # dependents go first
    assert plan.steps == (Step("uninstall", "woodpecker"), Step("uninstall", "forgejo"))


def test_a_consumer_survives_when_another_provider_remains() -> None:
    cat = catalog(
        mod("store-a", provides=["blob"]),
        mod("store-b", provides=["blob"]),
        mod("app", requires=["blob"]),
    )
    plan = plan_uninstall(cat, {"store-a", "store-b", "app"}, ["store-a"])
    assert plan.explicit == {"store-b", "app"}
    assert plan.cascade == ()
    assert plan.steps == (Step("uninstall", "store-a"),)


def test_uninstalling_something_not_installed_is_an_error() -> None:
    cat = real_shaped()
    with pytest.raises(NotInstalled):
        plan_uninstall(cat, {"forgejo"}, ["gitea"])


def test_a_dependency_cycle_is_reported() -> None:
    cat = catalog(
        mod("mod-a", provides=["x"], requires=["y"]),
        mod("mod-b", provides=["y"], requires=["x"]),
    )
    with pytest.raises(DependencyCycle):
        plan_install(cat, set(), ["mod-a"])


def test_links_connect_a_consumer_to_every_installed_provider() -> None:
    cat = catalog(
        mod("store-a", provides=["blob"]),
        mod("store-b", provides=["blob"]),
        mod("app", requires=["blob"]),
    )
    links = desired_links(cat, {"store-a", "store-b", "app"})
    assert links == {Link("app", "store-a", "blob"), Link("app", "store-b", "blob")}


def test_plans_do_not_depend_on_the_order_of_the_input() -> None:
    cat = real_shaped()
    forward = plan_install(cat, set(), ["agent-service", "ollama"], {"git": "forgejo"})
    backward = plan_install(cat, set(), ["ollama", "agent-service"], {"git": "forgejo"})
    assert forward == backward
    positions = {s.module: i for i, s in enumerate(forward.steps)}
    for provider, consumer in [
        ("forgejo", "woodpecker"),
        ("woodpecker", "agent-service"),
        ("litellm", "ollama"),
    ]:
        assert positions[provider] < positions[consumer]


# --- the v0.2 criterion on a catalogue shaped like the official one --------------------------

CHOICES = {"git": "forgejo"}
EVERYTHING = ["forgejo", "woodpecker", "litellm", "ollama", "agent-service", "preview-service"]


def _apply(explicit: frozenset[str], module: str, install: bool) -> frozenset[str]:
    cat = real_shaped()
    if install:
        return plan_install(cat, explicit, [module], CHOICES).explicit
    return plan_uninstall(cat, explicit, [module], CHOICES, confirm_cascade=True).explicit


def test_installing_in_any_order_reaches_the_same_state() -> None:
    cat = real_shaped()
    finals = set()
    for order in itertools.permutations(EVERYTHING):
        explicit: frozenset[str] = frozenset()
        for module in order:
            explicit = _apply(explicit, module, install=True)
        finals.add((explicit, resolve(cat, explicit, CHOICES).installed))
    assert len(finals) == 1
    ((explicit, installed),) = finals
    assert explicit == frozenset(EVERYTHING)
    assert installed == frozenset(EVERYTHING)


def test_uninstalling_in_any_order_ends_empty() -> None:
    cat = real_shaped()
    everything = frozenset(EVERYTHING)
    for order in itertools.permutations(EVERYTHING):
        explicit = everything
        for module in order:
            if module in resolve(cat, explicit, CHOICES).installed:
                explicit = _apply(explicit, module, install=False)
        assert explicit == frozenset()
        assert resolve(cat, explicit, CHOICES).installed == frozenset()


# --- hardware ---------------------------------------------------------------------------------

OLLAMA_VARIANTS = [
    {"id": "cpu", "gpu": "none", "min_ram_mb": 4096},
    {"id": "nvidia", "gpu": "nvidia", "min_ram_mb": 8192},
    {"id": "amd", "gpu": "amd", "min_ram_mb": 8192},
]


@pytest.mark.parametrize(
    ("hardware", "expected"),
    [
        (Hardware(ram_mb=16384, gpu="nvidia"), "nvidia"),
        (Hardware(ram_mb=16384, gpu="amd"), "amd"),
        (Hardware(ram_mb=16384, gpu="none"), "cpu"),
        (Hardware(ram_mb=6144, gpu="nvidia"), "cpu"),  # not enough RAM for the GPU variant
    ],
)
def test_the_best_variant_for_the_machine_is_chosen(hardware: Hardware, expected: str) -> None:
    manifest = mod("ollama", variants=OLLAMA_VARIANTS)
    variant = choose_variant(manifest, hardware)
    assert variant is not None
    assert variant.id == expected


def test_no_variant_fits_a_small_machine() -> None:
    manifest = mod("ollama", variants=OLLAMA_VARIANTS)
    with pytest.raises(NoCompatibleVariant) as info:
        choose_variant(manifest, Hardware(ram_mb=1024))
    assert {p.code for p in info.value.problems} >= {"ram"}


def test_a_module_without_variants_checks_its_own_requirements() -> None:
    plain = mod("small")
    assert choose_variant(plain, Hardware(ram_mb=512)) is None
    heavy = mod("heavy", min_ram_mb=8192)
    with pytest.raises(NoCompatibleVariant):
        choose_variant(heavy, Hardware(ram_mb=4096))
    needs_gpu = mod("gpu-only", gpu="nvidia")
    with pytest.raises(NoCompatibleVariant) as info:
        choose_variant(needs_gpu, Hardware(ram_mb=65536, gpu="amd"))
    assert info.value.problems[0].code == "gpu"


@pytest.mark.parametrize(
    ("needed", "host", "fits"),
    [
        ("none", "none", True),
        ("optional", "none", True),
        ("any", "none", False),
        ("any", "amd", True),
        ("nvidia", "amd", False),
        ("nvidia", "nvidia", True),
    ],
)
def test_gpu_requirements(needed: str, host: str, fits: bool) -> None:
    hardware = Hardware(ram_mb=1, gpu=host)  # type: ignore[arg-type]
    assert (not check_hardware(0, needed, hardware)) is fits
