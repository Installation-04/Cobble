"""Pure dependency resolution and planning for modules (no I/O, no Docker, no database).

The installed set is a *pure function* of what the user explicitly asked for:

    installed = resolve(catalog, explicit, choices)

Installing or uninstalling only edits `explicit`; a plan is the difference between two
resolutions. So every order of operations that ends with the same explicit set ends in the same
installed set (convergence), and a module that was only installed as a dependency disappears
when nothing needs it any more.

Rules (PLAN.md section 6):
- every capability a module `requires` must be provided by an installed module; a missing one is
  satisfied automatically when exactly one module can provide it, otherwise the caller must choose;
- a module that declares a capability `exclusive` must be its only installed provider;
- uninstalling never adds modules: dependents that would lose their last provider are removed too
  (a *cascade* the caller must confirm).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from .manifest import Manifest, Variant

Catalog = Mapping[str, Manifest]
Choices = Mapping[str, str]
HostGpu = Literal["none", "nvidia", "amd"]


# --- errors ------------------------------------------------------------------------------------


class ResolveError(Exception):
    """Base class: the request cannot be planned. The state is never changed by a failed plan."""


class UnknownModule(ResolveError):
    def __init__(self, module: str) -> None:
        super().__init__(f"unknown module {module!r}")
        self.module = module


class NotInstalled(ResolveError):
    def __init__(self, module: str) -> None:
        super().__init__(f"module {module!r} is not installed")
        self.module = module


class Unsatisfiable(ResolveError):
    def __init__(self, module: str, capability: str) -> None:
        super().__init__(f"{module!r} requires {capability!r} but no module provides it")
        self.module = module
        self.capability = capability


class NeedsChoice(ResolveError):
    """Several modules can provide a required capability: the caller must pick one."""

    def __init__(self, capability: str, candidates: Sequence[str]) -> None:
        super().__init__(f"choose a provider for {capability!r}: {', '.join(candidates)}")
        self.capability = capability
        self.candidates = tuple(candidates)


class InvalidChoice(ResolveError):
    def __init__(self, capability: str, module: str) -> None:
        super().__init__(f"{module!r} cannot provide {capability!r}")
        self.capability = capability
        self.module = module


class Conflict(ResolveError):
    """Two installed modules provide a capability one of them declares exclusive."""

    def __init__(self, capability: str, modules: Sequence[str]) -> None:
        super().__init__(f"exclusive capability {capability!r} provided by {', '.join(modules)}")
        self.capability = capability
        self.modules = tuple(modules)


class DependencyCycle(ResolveError):
    def __init__(self, modules: Sequence[str]) -> None:
        super().__init__(f"dependency cycle between {', '.join(modules)}")
        self.modules = tuple(modules)


class NeedsConfirmation(ResolveError):
    """Uninstalling would also remove modules the user asked for: confirm the cascade."""

    def __init__(self, cascade: Sequence[str]) -> None:
        super().__init__(f"this also removes: {', '.join(cascade)}")
        self.cascade = tuple(cascade)


class NoCompatibleVariant(ResolveError):
    def __init__(self, module: str, problems: Sequence[Incompatibility]) -> None:
        super().__init__(f"{module!r} does not fit this machine")
        self.module = module
        self.problems = tuple(problems)


# --- values ------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Hardware:
    """What the machine offers (detected elsewhere; this module only reasons about it)."""

    ram_mb: int
    gpu: HostGpu = "none"


@dataclass(frozen=True)
class Incompatibility:
    code: Literal["ram", "gpu"]
    needed: str
    have: str


@dataclass(frozen=True)
class Link:
    consumer: str
    provider: str
    capability: str


@dataclass(frozen=True)
class Step:
    action: Literal["install", "uninstall"]
    module: str


@dataclass(frozen=True)
class Resolution:
    installed: frozenset[str]
    auto_added: frozenset[str]
    links: frozenset[Link]


@dataclass(frozen=True)
class Plan:
    """What to do to go from one explicit set to another."""

    steps: tuple[Step, ...]
    explicit: frozenset[str]
    installed: frozenset[str]
    auto_added: tuple[str, ...] = ()
    cascade: tuple[str, ...] = ()
    replaced: tuple[str, ...] = ()
    auto_removed: tuple[str, ...] = ()
    links_added: frozenset[Link] = frozenset()
    links_removed: frozenset[Link] = frozenset()


# --- resolution --------------------------------------------------------------------------------


def providers_of(catalog: Catalog, capability: str) -> list[str]:
    """Every module that provides `capability`, sorted by id (deterministic)."""
    return sorted(
        module_id
        for module_id, manifest in catalog.items()
        if any(p.capability == capability for p in manifest.provides)
    )


def _provided(catalog: Catalog, module: str) -> set[str]:
    return {p.capability for p in catalog[module].provides}


def resolve(
    catalog: Catalog,
    explicit: frozenset[str] | set[str],
    choices: Choices | None = None,
    *,
    banned: frozenset[str] | set[str] = frozenset(),
) -> Resolution:
    """The installed set implied by `explicit`. Deterministic; raises a `ResolveError`.

    `banned` modules are never added as dependencies (used while planning an uninstall).
    """
    choices = choices or {}
    for module in explicit:
        if module not in catalog:
            raise UnknownModule(module)
    installed: set[str] = set(explicit)
    auto_added: set[str] = set()

    while True:
        missing = _first_missing(catalog, installed)
        if missing is None:
            break
        consumer, capability = missing
        candidates = [m for m in providers_of(catalog, capability) if m not in banned]
        chosen = choices.get(capability)
        if chosen is not None:
            if chosen not in candidates:
                raise InvalidChoice(capability, chosen)
            provider = chosen
        elif not candidates:
            raise Unsatisfiable(consumer, capability)
        elif len(candidates) == 1:
            provider = candidates[0]
        else:
            raise NeedsChoice(capability, candidates)
        installed.add(provider)
        auto_added.add(provider)

    _check_exclusive(catalog, installed)
    frozen = frozenset(installed)
    return Resolution(frozen, frozenset(auto_added), desired_links(catalog, frozen))


def _first_missing(catalog: Catalog, installed: set[str]) -> tuple[str, str] | None:
    provided: set[str] = set()
    for module in installed:
        provided |= _provided(catalog, module)
    for module in sorted(installed):
        for capability in catalog[module].requires:
            if capability not in provided:
                return module, capability
    return None


def _check_exclusive(catalog: Catalog, installed: set[str]) -> None:
    for module in sorted(installed):
        for capability in catalog[module].exclusive:
            providers = sorted(m for m in installed if capability in _provided(catalog, m))
            if providers != [module]:
                raise Conflict(capability, providers)


def desired_links(catalog: Catalog, installed: frozenset[str] | set[str]) -> frozenset[Link]:
    """Every (consumer, provider, capability) among the installed modules.

    A consumer is linked to *every* installed provider of a capability it requires. The
    module-manager reconciles this set with the stored links and runs the (idempotent) link and
    unlink hooks for the difference.
    """
    links: set[Link] = set()
    for consumer in installed:
        for capability in catalog[consumer].requires:
            for provider in installed:
                if provider != consumer and capability in _provided(catalog, provider):
                    links.add(Link(consumer, provider, capability))
    return frozenset(links)


def install_order(catalog: Catalog, modules: frozenset[str] | set[str]) -> list[str]:
    """Providers before the modules that depend on them; ties broken by id."""
    depends: dict[str, set[str]] = {
        m: {
            provider
            for capability in catalog[m].requires
            for provider in modules
            if provider != m and capability in _provided(catalog, provider)
        }
        for m in modules
    }
    order: list[str] = []
    remaining = dict(depends)
    while remaining:
        ready = sorted(m for m, deps in remaining.items() if not (deps & remaining.keys()))
        if not ready:
            raise DependencyCycle(sorted(remaining))
        order.extend(ready)
        for module in ready:
            del remaining[module]
    return order


# --- planning ----------------------------------------------------------------------------------


def _conflicts(catalog: Catalog, a: str, b: str) -> bool:
    shared = _provided(catalog, a) & _provided(catalog, b)
    return any(c in catalog[a].exclusive or c in catalog[b].exclusive for c in shared)


def _plan(
    catalog: Catalog,
    old: Resolution,
    new: Resolution,
    new_explicit: frozenset[str],
    *,
    cascade: tuple[str, ...] = (),
    replaced: tuple[str, ...] = (),
    auto_added: tuple[str, ...] = (),
    auto_removed: tuple[str, ...] = (),
) -> Plan:
    removed = old.installed - new.installed
    added = new.installed - old.installed
    uninstall_order = list(reversed(install_order(catalog, removed))) if removed else []
    steps = tuple(
        [Step("uninstall", m) for m in uninstall_order]
        + [Step("install", m) for m in install_order(catalog, added)]
    )
    return Plan(
        steps=steps,
        explicit=new_explicit,
        installed=new.installed,
        auto_added=auto_added,
        cascade=cascade,
        replaced=replaced,
        auto_removed=auto_removed,
        links_added=new.links - old.links,
        links_removed=old.links - new.links,
    )


def plan_install(
    catalog: Catalog,
    explicit: frozenset[str] | set[str],
    wanted: Sequence[str],
    choices: Choices | None = None,
    *,
    replace: bool = False,
) -> Plan:
    """Plan installing `wanted` (plus whatever they require).

    With `replace=True`, an explicit module that conflicts on an exclusive capability with a
    wanted one is swapped out instead of raising `Conflict`.
    """
    for module in wanted:
        if module not in catalog:
            raise UnknownModule(module)
    old = resolve(catalog, explicit, choices)
    new_explicit = set(explicit) | set(wanted)
    if replace:
        for module in sorted(explicit):
            if module not in wanted and any(_conflicts(catalog, module, w) for w in wanted):
                new_explicit.discard(module)
    new = resolve(catalog, new_explicit, choices)
    return _plan(
        catalog,
        old,
        new,
        frozenset(new_explicit),
        replaced=tuple(sorted(set(explicit) - new_explicit)),
        auto_added=tuple(sorted(new.installed - old.installed - set(wanted))),
        auto_removed=tuple(sorted((old.installed - new.installed) - set(explicit))),
    )


def plan_uninstall(
    catalog: Catalog,
    explicit: frozenset[str] | set[str],
    removed: Sequence[str],
    choices: Choices | None = None,
    *,
    confirm_cascade: bool = False,
) -> Plan:
    """Plan uninstalling `removed`; dependents that lose their last provider go with them."""
    old = resolve(catalog, explicit, choices)
    for module in removed:
        if module not in catalog:
            raise UnknownModule(module)
        if module not in old.installed:
            raise NotInstalled(module)

    gone: set[str] = set(removed)
    changed = True
    while changed:
        changed = False
        for module in sorted(old.installed - gone):
            for capability in catalog[module].requires:
                survivors = [
                    m
                    for m in old.installed - gone
                    if m != module and capability in _provided(catalog, m)
                ]
                if not survivors:
                    gone.add(module)
                    changed = True
                    break

    cascade = tuple(sorted((gone - set(removed)) & set(explicit)))
    if cascade and not confirm_cascade:
        raise NeedsConfirmation(cascade)
    new_explicit = frozenset(set(explicit) - gone)
    kept_choices = {c: m for c, m in (choices or {}).items() if m not in gone}
    new = resolve(catalog, new_explicit, kept_choices, banned=gone)
    return _plan(
        catalog,
        old,
        new,
        new_explicit,
        cascade=cascade,
        auto_removed=tuple(sorted((old.installed - new.installed) - set(explicit) - set(removed))),
    )


# --- hardware ----------------------------------------------------------------------------------


def _gpu_fits(needed: str, host: HostGpu) -> bool:
    if needed in ("none", "optional"):
        return True
    if needed == "any":
        return host != "none"
    return needed == host


def check_hardware(min_ram_mb: int, gpu: str, hardware: Hardware) -> list[Incompatibility]:
    """Why a (module or variant) requirement does not fit this machine; empty when it does."""
    problems: list[Incompatibility] = []
    if hardware.ram_mb < min_ram_mb:
        problems.append(Incompatibility("ram", str(min_ram_mb), str(hardware.ram_mb)))
    if not _gpu_fits(gpu, hardware.gpu):
        problems.append(Incompatibility("gpu", gpu, hardware.gpu))
    return problems


_GPU_RANK = {"nvidia": 3, "amd": 3, "any": 2, "optional": 1, "none": 0}


def choose_variant(manifest: Manifest, hardware: Hardware) -> Variant | None:
    """The best variant for this machine, or None for a module without variants.

    A variant that uses the machine's GPU beats a generic one, which beats the CPU one. Raises
    `NoCompatibleVariant` with the reasons when nothing fits (the Store greys the module out).
    """
    base = check_hardware(manifest.hardware.min_ram_mb, manifest.hardware.gpu, hardware)
    if base:
        raise NoCompatibleVariant(manifest.id, base)
    if not manifest.variants:
        return None
    fitting = [v for v in manifest.variants if not check_hardware(v.min_ram_mb, v.gpu, hardware)]
    if not fitting:
        problems = [
            p for v in manifest.variants for p in check_hardware(v.min_ram_mb, v.gpu, hardware)
        ]
        raise NoCompatibleVariant(manifest.id, problems)
    return sorted(fitting, key=lambda v: (-_GPU_RANK[v.gpu], v.id))[0]
