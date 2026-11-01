from __future__ import annotations

import copy
import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from cobble_sdk import ManifestError, load_manifest, parse_manifest
from cobble_sdk.schema import TARGET, render

SDK = Path(__file__).resolve().parent.parent
DIGEST = "a" * 64

FORGEJO: dict[str, Any] = {
    "id": "forgejo",
    "name": "Forgejo",
    "version": "15.0.11",
    "category": "git",
    "description": {"fr": "Serveur Git léger", "en": "Lightweight Git server"},
    "license": "GPL-3.0-or-later",
    "provides": [{"capability": "git", "adapter": "forgejo-api"}],
    "exclusive": ["git"],
    "hardware": {"min_ram_mb": 512, "gpu": "none"},
    "images": [f"codeberg.org/forgejo/forgejo:15.0.11-rootless@sha256:{DIGEST}"],
    "web_ui": {"service": "forgejo", "port": 3000, "path": "/git"},
    "settings": [{"key": "admin_email", "type": "email", "default": "admin@example.com"}],
    "secrets": ["admin_password", "api_token"],
    "healthcheck": {"http": "/api/healthz", "interval": "10s"},
    "hooks": {"register_core": "hooks/register-core.sh", "on_unlink": {"ci": "hooks/unlink-ci.sh"}},
    "backup": {"volumes": ["data"]},
    "offline": True,
}
# A CI module that needs a git provider. Forgejo above has an `on_unlink` hook for `ci`: a forge
# reacts to a CI module being linked (for example it creates the OAuth application).
WOODPECKER: dict[str, Any] = {
    **FORGEJO,
    "id": "woodpecker",
    "name": "Woodpecker",
    "category": "ci",
    "provides": [{"capability": "ci", "adapter": "woodpecker-api"}],
    "requires": ["git"],
    "exclusive": ["ci"],
    "web_ui": {"service": "woodpecker-server", "port": 8000, "path": "/ci"},
    "hooks": {"on_link": {"git": "hooks/link-git.sh"}, "on_unlink": {"git": "hooks/unlink-git.sh"}},
    "host_access": ["docker_socket"],
}


def _with(**changes: Any) -> dict[str, Any]:
    data = copy.deepcopy(FORGEJO)
    data.update(changes)
    return data


def test_valid_manifests_load() -> None:
    forgejo = parse_manifest(FORGEJO)
    assert forgejo.id == "forgejo"
    assert forgejo.provides[0].capability == "git"
    assert forgejo.provides[0].adapter == "forgejo-api"
    assert forgejo.hardware.min_ram_mb == 512
    woodpecker = parse_manifest(WOODPECKER)
    assert woodpecker.requires == ["git"]
    assert woodpecker.host_access == ["docker_socket"]


def test_provides_shorthand_and_defaults() -> None:
    manifest = parse_manifest(_with(provides=["git"]))
    assert manifest.provides[0].capability == "git"
    assert manifest.provides[0].adapter is None
    minimal = {
        key: FORGEJO[key]
        for key in ("id", "name", "version", "category", "description", "license", "images")
    }
    parsed = parse_manifest(minimal)
    assert parsed.compose == "compose.yml"
    assert parsed.host_access == []
    assert parsed.core_secrets == []
    assert parsed.link_secrets == [] and parsed.hooks.pre_up is None
    assert parsed.offline is False


INVALID: list[tuple[str, dict[str, Any], str]] = [
    ("bad id", _with(id="Forgejo!"), "id"),
    ("id too short", _with(id="a"), "id"),
    ("bad version", _with(version="v1"), "version"),
    ("missing french text", _with(description={"en": "x"}), "description.fr"),
    ("empty english text", _with(description={"fr": "x", "en": ""}), "description.en"),
    ("unknown field", _with(colour="blue"), "colour"),
    ("no image", _with(images=[]), "images"),
    ("tag only image", _with(images=["forgejo/forgejo:15"]), "pinned by digest"),
    ("latest tag", _with(images=[f"forgejo/forgejo:latest@sha256:{DIGEST}"]), "latest"),
    ("short digest", _with(images=["forgejo/forgejo@sha256:abc"]), "pinned by digest"),
    (
        "duplicate image",
        _with(images=[f"a/b@sha256:{DIGEST}", f"a/b@sha256:{DIGEST}"]),
        "duplicate",
    ),
    ("duplicate capability", _with(provides=["git", "git"]), "duplicate"),
    ("exclusive not provided", _with(exclusive=["ci"]), "exclusive"),
    ("requires own capability", _with(requires=["git"]), "cannot require"),
    ("setting is also a secret", _with(secrets=["admin_email"]), "both a setting and a secret"),
    ("duplicate setting", _with(settings=[{"key": "a"}, {"key": "a"}]), "duplicate"),
    ("select without options", _with(settings=[{"key": "mode", "type": "select"}]), "options"),
    (
        "select default outside options",
        _with(settings=[{"key": "m", "type": "select", "options": ["a"], "default": "b"}]),
        "default",
    ),
    ("options on a text setting", _with(settings=[{"key": "m", "options": ["a"]}]), "options"),
    ("port zero", _with(web_ui={"service": "forgejo", "port": 0, "path": "/git"}), "web_ui.port"),
    (
        "port too high",
        _with(web_ui={"service": "forgejo", "port": 70000, "path": "/git"}),
        "web_ui.port",
    ),
    (
        "path without slash",
        _with(web_ui={"service": "forgejo", "port": 1, "path": "git"}),
        "web_ui.path",
    ),
    ("path traversal", _with(web_ui={"service": "forgejo", "port": 1, "path": "/a/../b"}), "'..'"),
    ("bad interval", _with(healthcheck={"http": "/h", "interval": "soon"}), "interval"),
    ("absolute hook", _with(hooks={"register_core": "/bin/sh"}), "relative path"),
    ("hook escapes the module", _with(hooks={"post_install": "../x.sh"}), "relative path"),
    ("hook with a bad capability name", _with(hooks={"on_link": {"Bad Name": "h.sh"}}), "on_link"),
    ("absolute compose path", _with(compose="/etc/passwd"), "relative path"),
    ("unknown host access", _with(host_access=["privileged"]), "host_access"),
    ("unknown gpu kind", _with(hardware={"gpu": "tpu"}), "hardware.gpu"),
    ("negative ram", _with(hardware={"min_ram_mb": -1}), "min_ram_mb"),
    ("web_ui without a service", _with(web_ui={"port": 1, "path": "/git"}), "web_ui.service"),
    ("duplicate bus service", _with(bus=["forgejo", "forgejo"]), "duplicate"),
    (
        "duplicate link secret",
        _with(link_secrets=["admin_password", "admin_password"]),
        "duplicate",
    ),
    ("hostile pre_up path", _with(hooks={"pre_up": "../x.sh"}), "relative path"),
    ("duplicate core secret", _with(core_secrets=["api_token", "api_token"]), "duplicate"),
    ("bad core secret name", _with(core_secrets=["Api Token"]), "core_secrets"),
    ("duplicate variant", _with(variants=[{"id": "cpu"}, {"id": "cpu"}]), "duplicate"),
]


@pytest.mark.parametrize(("data", "needle"), [c[1:] for c in INVALID], ids=[c[0] for c in INVALID])
def test_invalid_manifests_are_rejected_with_a_located_message(
    data: dict[str, Any], needle: str
) -> None:
    with pytest.raises(ManifestError) as info:
        parse_manifest(data)
    assert any(needle in problem for problem in info.value.problems), info.value.problems


def test_a_manifest_must_be_a_mapping() -> None:
    with pytest.raises(ManifestError, match="mapping"):
        parse_manifest(["not", "a", "mapping"])


def test_load_manifest_reads_yaml(tmp_path: Path) -> None:
    path = tmp_path / "manifest.yaml"
    path.write_text(yaml.safe_dump(FORGEJO), "utf-8")
    assert load_manifest(path).id == "forgejo"


def test_load_manifest_reports_unreadable_and_broken_files(tmp_path: Path) -> None:
    with pytest.raises(ManifestError, match="<file>"):
        load_manifest(tmp_path / "missing.yaml")
    broken = tmp_path / "broken.yaml"
    broken.write_text("id: [unclosed\n", "utf-8")
    with pytest.raises(ManifestError, match="<file>"):
        load_manifest(broken)


def test_manifests_are_immutable() -> None:
    manifest = parse_manifest(FORGEJO)
    with pytest.raises(ValueError, match="frozen"):
        manifest.id = "other"  # type: ignore[misc]


def test_the_checked_in_json_schema_is_in_sync() -> None:
    assert TARGET.read_text("utf-8") == render(), "run `uv run python -m cobble_sdk.schema`"


def test_the_sdk_never_imports_the_agpl_core() -> None:
    """sdk/ is Apache-2.0: it must stay free of any dependency on the AGPL `cobble` package."""
    offenders = [
        str(path)
        for path in (SDK / "cobble_sdk").rglob("*.py")
        if re.search(r"^\s*(?:from|import)\s+cobble(?:\.|\s|$)", path.read_text("utf-8"), re.M)
    ]
    assert offenders == []


# --- language-model backends ------------------------------------------------------------------

LLM: dict[str, Any] = {
    "service": "ollama",
    "port": 11434,
    "models": [
        {
            "name": "coder-small",
            "model": "ollama_chat/qwen2.5-coder:1.5b",
            "pull": "qwen2.5-coder:1.5b",
        }
    ],
}


def _llm(**fields: Any) -> dict[str, Any]:
    return _with(
        **{"provides": ["llm-backend"], "exclusive": [], "requires": [], "llm": LLM, **fields}
    )


def test_a_language_model_backend_declares_where_it_listens_and_what_it_serves() -> None:
    parsed = parse_manifest(_llm())
    assert parsed.llm is not None and parsed.llm.port == 11434
    assert [m.name for m in parsed.llm_models()] == ["coder-small"]
    assert parsed.llm_models("anything") == parsed.llm_models()  # no variant: the default models


def test_a_variant_may_serve_other_models() -> None:
    big = {"name": "coder", "model": "ollama_chat/qwen2.5-coder:7b", "pull": "qwen2.5-coder:7b"}
    parsed = parse_manifest(
        _llm(variants=[{"id": "cpu"}, {"id": "nvidia", "gpu": "nvidia", "models": [big]}])
    )
    assert [m.name for m in parsed.llm_models("nvidia")] == ["coder"]
    assert [m.name for m in parsed.llm_models("cpu")] == ["coder-small"]


@pytest.mark.parametrize(
    ("label", "fields", "fragment"),
    [
        ("llm without the capability", _with(llm=LLM), "llm-backend"),
        ("variant models without llm", _with(variants=[{"id": "a", "models": []}]), "llm"),
        ("duplicate model names", _llm(llm={**LLM, "models": LLM["models"] * 2}), "duplicate"),
        (
            "hostile model string",
            _llm(llm={**LLM, "models": [{"name": "x", "model": "ollama/a\nmodel_list: []"}]}),
            "llm.models",
        ),
        (
            "hostile model name",
            _llm(llm={**LLM, "models": [{"name": "Bad Name", "model": "ollama/a"}]}),
            "llm.models",
        ),
        (
            "hostile pull",
            _llm(
                llm={**LLM, "models": [{"name": "x", "model": "ollama/a", "pull": "a; rm -rf /"}]}
            ),
            "pull",
        ),
    ],
)
def test_bad_llm_declarations_are_rejected(
    label: str, fields: dict[str, Any], fragment: str
) -> None:
    with pytest.raises(ManifestError) as caught:
        parse_manifest(fields)
    assert fragment in str(caught.value), label


def test_a_variant_may_bring_its_own_compose_file_inside_the_module() -> None:
    parsed = parse_manifest(
        _with(variants=[{"id": "nvidia", "gpu": "nvidia", "compose": "compose.nvidia.yml"}])
    )
    assert parsed.variants[0].compose == "compose.nvidia.yml"
    for bad in ("../x.yml", "/etc/passwd"):
        with pytest.raises(ManifestError):
            parse_manifest(_with(variants=[{"id": "a", "compose": bad}]))
