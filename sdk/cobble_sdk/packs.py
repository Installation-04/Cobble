"""Starter packs: named sets of modules offered at first launch, chosen for the machine.

A pack is a small YAML file in the catalogue (`catalog/packs/<id>.yaml`). Installing a pack is
installing its modules in one operation: nothing here changes how modules are installed. Like
the resolver, everything is a pure function (the machine is described by `Hardware`).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from pydantic import Field, ValidationError, model_validator

from .manifest import Hardware as PackHardware
from .manifest import Localized, Manifest, ModuleId, _Strict, _unique
from .resolve import (
    Hardware,
    NoCompatibleVariant,
    ResolveError,
    check_hardware,
    choose_variant,
    plan_install,
)


class Pack(_Strict):
    id: ModuleId
    name: Localized
    description: Localized
    modules: list[ModuleId] = Field(min_length=1, max_length=20)
    # What the machine must offer for this pack to make sense, on top of what each module needs
    # (for example a GPU for the pack that runs models locally on it).
    hardware: PackHardware = Field(default_factory=PackHardware)
    # Among the packs that fit a machine, the highest priority is the one recommended.
    priority: int = Field(default=0, ge=0, le=100)

    @model_validator(mode="after")
    def _consistent(self) -> Pack:
        _unique(self.modules, "modules")
        return self


class PackError(ValueError):
    """A pack file is invalid. `problems` lists `location: message` lines."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


def parse_pack(data: object) -> Pack:
    if not isinstance(data, dict):
        raise PackError(["<root>: a pack must be a mapping"])
    try:
        return Pack.model_validate(data)
    except ValidationError as exc:
        raise PackError(
            [
                f"{'.'.join(str(part) for part in err['loc']) or '<root>'}: {err['msg']}"
                for err in exc.errors()
            ]
        ) from None


def load_pack(path: Path | str) -> Pack:
    try:
        data = yaml.safe_load(Path(path).read_text("utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise PackError([f"<file>: {exc}"]) from None
    return parse_pack(data)


def load_packs(directory: Path | str) -> tuple[dict[str, Pack], dict[str, list[str]]]:
    """Every valid pack of a directory, and the problems of the invalid ones (by file name)."""
    packs: dict[str, Pack] = {}
    problems: dict[str, list[str]] = {}
    root = Path(directory)
    if not root.is_dir():
        return packs, problems
    for path in sorted(root.glob("*.yaml")):
        try:
            pack = load_pack(path)
        except PackError as exc:
            problems[path.stem] = list(exc.problems)
            continue
        if pack.id != path.stem:
            problems[path.stem] = [f"id: {pack.id!r} does not match the file name"]
            continue
        packs[pack.id] = pack
    return packs, problems


def check_pack(pack: Pack, manifests: Mapping[str, Manifest]) -> list[str]:
    """Why a pack cannot work with this catalogue (empty when it can).

    Every module must exist, and together they must resolve with nothing left to choose: the
    first-run wizard installs a pack without asking which provider to use.
    """
    unknown = [m for m in pack.modules if m not in manifests]
    if unknown:
        return [f"unknown module: {m}" for m in unknown]
    try:
        plan_install(manifests, frozenset(), pack.modules)
    except ResolveError as exc:
        return [f"{type(exc).__name__}: {exc}"]
    return []


@dataclass(frozen=True)
class PackProblem:
    """One reason a pack does not fit: `module` is None when the pack itself asks for it."""

    module: str | None
    code: str
    needed: str
    have: str


@dataclass(frozen=True)
class PackFit:
    ok: bool
    problems: tuple[PackProblem, ...] = ()


def pack_fit(pack: Pack, manifests: Mapping[str, Manifest], hardware: Hardware) -> PackFit:
    """Does this pack fit the machine: its own requirement and every module's."""
    problems = [
        PackProblem(None, p.code, p.needed, p.have)
        for p in check_hardware(pack.hardware.min_ram_mb, pack.hardware.gpu, hardware)
    ]
    for module in pack.modules:
        manifest = manifests.get(module)
        if manifest is None:
            continue
        try:
            choose_variant(manifest, hardware)
        except NoCompatibleVariant as exc:
            problems += [PackProblem(module, p.code, p.needed, p.have) for p in exc.problems]
    return PackFit(not problems, tuple(problems))


def recommend(
    packs: Mapping[str, Pack], manifests: Mapping[str, Manifest], hardware: Hardware
) -> str | None:
    """The pack to propose first: the fitting one with the highest priority (ties: by id)."""
    fitting = [p for p in packs.values() if pack_fit(p, manifests, hardware).ok]
    if not fitting:
        return None
    return sorted(fitting, key=lambda p: (-p.priority, p.id))[0].id


def pack_json_schema() -> dict[str, Any]:
    schema = Pack.model_json_schema()
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["title"] = "Cobble starter pack"
    return schema
