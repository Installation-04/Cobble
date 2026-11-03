"""Starter packs: parsing, loading, checking against a catalogue, fit and recommendation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from cobble_sdk import (
    Hardware,
    Manifest,
    PackError,
    check_pack,
    load_pack,
    load_packs,
    pack_fit,
    parse_manifest,
    parse_pack,
    recommend,
)

from .catalogs import DIGEST


def module(module_id: str, **fields: Any) -> Manifest:
    data: dict[str, Any] = {
        "id": module_id,
        "name": module_id,
        "version": "1.0.0",
        "category": "test",
        "description": {"fr": "x", "en": "x"},
        "license": "MIT",
        "images": [f"example.org/{module_id}:1@sha256:{DIGEST}"],
    }
    data.update(fields)
    return parse_manifest(data)


CATALOG: dict[str, Manifest] = {
    m.id: m
    for m in (
        module("forgejo", provides=["git"], exclusive=["git"]),
        module("gitea", provides=["git"], exclusive=["git"]),
        module("woodpecker", provides=["ci"], requires=["git"]),
        module("orphan", requires=["nothing-provides-this"]),
        module(
            "ollama",
            provides=["llm-backend"],
            variants=[
                {"id": "gpu", "gpu": "any", "min_ram_mb": 8192},
                {"id": "cpu", "gpu": "none", "min_ram_mb": 4096},
            ],
        ),
        module("huge", hardware={"min_ram_mb": 65536}),
    )
}


def pack_data(pack_id: str = "demo", **fields: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": pack_id,
        "name": {"fr": "Démo", "en": "Demo"},
        "description": {"fr": "Un pack", "en": "A pack"},
        "modules": ["forgejo", "woodpecker"],
    }
    data.update(fields)
    return data


# --- parsing ------------------------------------------------------------------------------------


def test_a_pack_has_sensible_defaults() -> None:
    pack = parse_pack(pack_data())
    assert pack.modules == ["forgejo", "woodpecker"]
    assert pack.hardware.min_ram_mb == 0 and pack.hardware.gpu == "none" and pack.priority == 0


@pytest.mark.parametrize(
    ("label", "change", "fragment"),
    [
        ("no modules", {"modules": []}, "modules"),
        ("too many modules", {"modules": [f"m{i}" for i in range(21)]}, "modules"),
        ("duplicate module", {"modules": ["forgejo", "forgejo"]}, "duplicate"),
        ("hostile module id", {"modules": ["../etc"]}, "modules.0"),
        ("hostile pack id", {"id": "A b"}, "id"),
        ("priority too high", {"priority": 101}, "priority"),
        ("negative priority", {"priority": -1}, "priority"),
        ("unknown field", {"surprise": True}, "surprise"),
        ("missing english", {"name": {"fr": "x"}}, "name.en"),
        ("bad gpu kind", {"hardware": {"gpu": "quantum"}}, "hardware.gpu"),
    ],
)
def test_bad_packs_are_rejected_with_the_location(
    label: str, change: dict[str, Any], fragment: str
) -> None:
    with pytest.raises(PackError) as caught:
        parse_pack(pack_data(**change))
    assert fragment in str(caught.value), label


def test_a_pack_must_be_a_mapping() -> None:
    with pytest.raises(PackError):
        parse_pack(["not", "a", "mapping"])


# --- loading ------------------------------------------------------------------------------------


def write(directory: Path, name: str, data: Any) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    text = data if isinstance(data, str) else yaml.safe_dump(data)
    (directory / name).write_text(text)


def test_load_packs_reads_the_valid_ones_and_reports_the_others(tmp_path: Path) -> None:
    write(tmp_path, "demo.yaml", pack_data("demo"))
    write(tmp_path, "renamed.yaml", pack_data("other-id"))
    write(tmp_path, "broken.yaml", {"id": "broken"})
    write(tmp_path, "garbage.yaml", "::: not yaml: [")
    write(tmp_path, "notes.txt", "ignored")
    packs, problems = load_packs(tmp_path)
    assert set(packs) == {"demo"}
    assert set(problems) == {"renamed", "broken", "garbage"}
    assert "does not match the file name" in problems["renamed"][0]


def test_load_packs_of_a_missing_directory_is_empty(tmp_path: Path) -> None:
    assert load_packs(tmp_path / "absent") == ({}, {})


def test_load_pack_reports_an_unreadable_file(tmp_path: Path) -> None:
    with pytest.raises(PackError):
        load_pack(tmp_path / "nope.yaml")


# --- checking against the catalogue --------------------------------------------------------------


def test_a_pack_of_known_modules_that_resolve_is_fine() -> None:
    assert check_pack(parse_pack(pack_data()), CATALOG) == []


def test_unknown_modules_are_named() -> None:
    pack = parse_pack(pack_data(modules=["forgejo", "ghost", "phantom"]))
    assert check_pack(pack, CATALOG) == ["unknown module: ghost", "unknown module: phantom"]


def test_a_pack_that_cannot_resolve_is_reported() -> None:
    problems = check_pack(parse_pack(pack_data(modules=["orphan"])), CATALOG)
    assert len(problems) == 1 and problems[0].startswith("Unsatisfiable")


def test_a_pack_must_not_leave_a_provider_to_choose() -> None:
    # woodpecker needs git and two modules provide it: the wizard cannot ask, the pack must say
    # which. A pack that names forgejo resolves; one that names neither does not.
    ambiguous = parse_pack(pack_data(modules=["woodpecker"]))
    problems = check_pack(ambiguous, CATALOG)
    assert len(problems) == 1 and problems[0].startswith("NeedsChoice")


# --- fit and recommendation ----------------------------------------------------------------------

LOCAL_GPU = parse_pack(
    pack_data(
        "local-gpu",
        modules=["forgejo", "woodpecker", "ollama"],
        hardware={"min_ram_mb": 8192, "gpu": "any"},
        priority=30,
    )
)
LOCAL_CPU = parse_pack(
    pack_data(
        "local-cpu",
        modules=["forgejo", "woodpecker", "ollama"],
        hardware={"min_ram_mb": 8192},
        priority=20,
    )
)
API_ONLY = parse_pack(
    pack_data(
        "api-only", modules=["forgejo", "woodpecker"], hardware={"min_ram_mb": 4096}, priority=10
    )
)
PACKS = {p.id: p for p in (LOCAL_GPU, LOCAL_CPU, API_ONLY)}


def test_the_pack_needs_the_gpu_it_asks_for() -> None:
    assert pack_fit(LOCAL_GPU, CATALOG, Hardware(ram_mb=16384, gpu="nvidia")).ok
    fit = pack_fit(LOCAL_GPU, CATALOG, Hardware(ram_mb=16384, gpu="none"))
    assert not fit.ok
    assert [(p.module, p.code, p.needed, p.have) for p in fit.problems] == [
        (None, "gpu", "any", "none")
    ]


def test_the_pack_needs_the_memory_it_asks_for() -> None:
    fit = pack_fit(LOCAL_CPU, CATALOG, Hardware(ram_mb=6000))
    assert not fit.ok
    assert any(p.module is None and p.code == "ram" and p.needed == "8192" for p in fit.problems)


def test_a_module_that_does_not_fit_makes_the_pack_not_fit_and_is_named() -> None:
    pack = parse_pack(pack_data("big", modules=["forgejo", "huge"]))
    fit = pack_fit(pack, CATALOG, Hardware(ram_mb=16384))
    assert not fit.ok
    assert [(p.module, p.code) for p in fit.problems] == [("huge", "ram")]


@pytest.mark.parametrize(
    ("ram_mb", "gpu", "expected"),
    [
        (32768, "nvidia", "local-gpu"),
        (16384, "amd", "local-gpu"),
        (16384, "none", "local-cpu"),
        (8192, "none", "local-cpu"),
        (6000, "none", "api-only"),
        (4096, "none", "api-only"),
        (2048, "none", None),
        (4096, "nvidia", "api-only"),  # a GPU but too little memory for the local packs
    ],
)
def test_the_recommended_pack_follows_the_machine(
    ram_mb: int, gpu: str, expected: str | None
) -> None:
    assert recommend(PACKS, CATALOG, Hardware(ram_mb=ram_mb, gpu=gpu)) == expected  # type: ignore[arg-type]


def test_a_tie_in_priority_is_settled_by_id_so_the_answer_is_stable() -> None:
    a = parse_pack(pack_data("alpha", priority=5))
    b = parse_pack(pack_data("beta", priority=5))
    assert recommend({"beta": b, "alpha": a}, CATALOG, Hardware(ram_mb=8192)) == "alpha"
    assert recommend({"alpha": a, "beta": b}, CATALOG, Hardware(ram_mb=8192)) == "alpha"
