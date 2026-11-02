"""The proxy route is built from validated fields only."""

from __future__ import annotations

from typing import Any

import pytest

from cobble_sdk import ManifestError, parse_manifest, render_route, upstream

DIGEST = "a" * 64


def make(**fields: Any) -> Any:
    data: dict[str, Any] = {
        "id": "forgejo",
        "name": "Forgejo",
        "version": "1.0.0",
        "category": "git",
        "description": {"fr": "Git", "en": "Git"},
        "license": "MIT",
        "images": [f"example.org/forgejo:1@sha256:{DIGEST}"],
        "web_ui": {"service": "web", "port": 3000, "path": "/git"},
    }
    data.update(fields)
    return parse_manifest(data)


def test_a_module_is_exposed_under_its_path_and_the_prefix_is_stripped_by_default() -> None:
    route = render_route(make())
    assert route is not None
    assert "handle_path /git/* {" in route
    assert "reverse_proxy cobble-forgejo-web:3000" in route
    assert upstream(make()) == "cobble-forgejo-web:3000"


def test_a_product_that_knows_its_prefix_keeps_it() -> None:
    route = render_route(
        make(web_ui={"service": "web", "port": 8000, "path": "/ci", "strip_prefix": False})
    )
    assert route is not None and route.splitlines()[1].startswith("handle /ci/* {")


def test_no_web_ui_or_root_path_means_no_route() -> None:
    assert render_route(make(web_ui=None)) is None
    assert upstream(make(web_ui=None)) is None
    assert render_route(make(web_ui={"service": "web", "port": 80, "path": "/"})) is None


@pytest.mark.parametrize("path", ["/a b", "/x}\nreverse_proxy evil:1", "/a;b", "/../x", "git"])
def test_a_hostile_path_cannot_reach_the_proxy_configuration(path: str) -> None:
    with pytest.raises(ManifestError):
        make(web_ui={"service": "web", "port": 80, "path": path})


def test_a_non_public_service_is_reachable_by_the_core_but_has_no_route() -> None:
    manifest = make(web_ui={"service": "api", "port": 8090, "path": "/agents", "public": False})
    assert render_route(manifest) is None
    assert upstream(manifest) == "cobble-forgejo-api:8090"  # connections() still reports it
    assert render_route(make()) is not None  # public by default
