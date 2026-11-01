from __future__ import annotations

import copy
from collections.abc import Callable
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from cobble_sdk import ComposeRejected, Limits, parse_manifest, rewrite_compose

from .catalogs import DIGEST
from .test_manifest import WOODPECKER

MODULE_DIR = "/opt/cobble/modules/woodpecker"
SERVER_IMAGE = f"woodpeckerci/woodpecker-server:v3@sha256:{DIGEST}"
AGENT_IMAGE = f"woodpeckerci/woodpecker-agent:v3@sha256:{DIGEST}"


def manifest(**changes: Any) -> Any:
    data = copy.deepcopy(WOODPECKER)
    data["images"] = [SERVER_IMAGE, AGENT_IMAGE]
    data["web_ui"] = {"service": "server", "port": 8000, "path": "/ci"}
    data["host_access"] = ["docker_socket"]
    data.update(changes)
    return parse_manifest(data)


def base_compose() -> dict[str, Any]:
    """Shaped like `docker compose config --format json` of a small CI module."""
    return {
        "name": "whatever",
        "services": {
            "server": {
                "image": SERVER_IMAGE,
                "container_name": "woodpecker-server",
                "ports": [{"target": 8000, "published": "8000", "protocol": "tcp"}],
                "networks": {"pack": {"aliases": ["ci-server"]}, "core": {}},
                "volumes": [{"type": "volume", "source": "data", "target": "/data"}],
                "environment": {"A": "1"},
            },
            "agent": {
                "image": AGENT_IMAGE,
                "networks": {"pack": {}},
                "volumes": [
                    {
                        "type": "bind",
                        "source": "/var/run/docker.sock",
                        "target": "/var/run/docker.sock",
                    },
                    {
                        "type": "bind",
                        "source": f"{MODULE_DIR}/conf",
                        "target": "/conf",
                        "read_only": True,
                    },
                ],
                "mem_limit": 2147483648,
            },
            "helper": {"image": SERVER_IMAGE},
        },
        "networks": {
            "pack": {"name": "cobble-pack-internal", "internal": True},
            "core": {"name": "cobble_core", "external": True},
        },
        "volumes": {"data": {"name": "woodpecker_data"}},
    }


def rewrite(compose: dict[str, Any], **kw: Any) -> Any:
    return rewrite_compose(compose, kw.pop("manifest", manifest()), module_dir=MODULE_DIR, **kw)


def test_the_module_is_namespaced_and_stripped_of_host_ports() -> None:
    result = rewrite(base_compose()).compose
    assert result["name"] == "cobble-woodpecker"
    assert result["volumes"]["data"]["name"] == "cobble-woodpecker-data"
    assert result["networks"]["pack"] == {
        "name": "cobble-woodpecker-pack",
        "internal": True,
    }
    server = result["services"]["server"]
    assert "ports" not in server
    assert server["container_name"] == "cobble-woodpecker-server"
    assert server["labels"] == {
        "cobble.managed": "true",
        "cobble.module": "woodpecker",
        "cobble.service": "server",
    }
    assert server["restart"] == "unless-stopped"
    assert server["networks"]["pack"] == {"aliases": ["ci-server"]}


def test_only_declared_services_join_the_shared_network_with_a_unique_alias() -> None:
    result = rewrite(base_compose())
    assert result.bus_aliases == {"server": "cobble-woodpecker-server"}
    assert result.compose["networks"]["bus"] == {"name": "cobble_core", "external": True}
    server_nets = result.compose["services"]["server"]["networks"]
    assert server_nets["bus"] == {"aliases": ["cobble-woodpecker-server"]}
    assert "core" not in server_nets  # the declared external key is replaced by the managed one
    assert "bus" not in result.compose["services"]["agent"]["networks"]
    # a service with no networks of its own keeps the project's default network
    helper = result.compose["services"]["helper"]
    assert "networks" not in helper


def test_a_declared_bus_service_without_networks_keeps_reaching_its_siblings() -> None:
    compose = base_compose()
    result = rewrite(compose, manifest=manifest(bus=["helper"]))
    helper = result.compose["services"]["helper"]
    assert set(helper["networks"]) == {"default", "bus"}
    assert result.compose["networks"]["default"] == {"name": "cobble-woodpecker_default"}


def test_default_limits_apply_only_where_the_module_set_none() -> None:
    result = rewrite(base_compose(), limits=Limits(cpus=0.5, memory_bytes=1000, pids=64)).compose
    agent = result["services"]["agent"]
    assert agent["mem_limit"] == 2147483648  # the module's own value is kept
    assert (agent["cpus"], agent["pids_limit"]) == (0.5, 64)
    assert result["services"]["server"]["mem_limit"] == 1000


def test_deploy_limits_count_as_limits() -> None:
    compose = base_compose()
    compose["services"]["server"]["deploy"] = {
        "resources": {"limits": {"memory": "1g", "cpus": "2"}}
    }
    server = rewrite(compose).compose["services"]["server"]
    assert "mem_limit" not in server
    assert "cpus" not in server
    assert "pids_limit" in server


def test_the_docker_socket_needs_the_declared_exception() -> None:
    with pytest.raises(ComposeRejected) as info:
        rewrite(base_compose(), manifest=manifest(host_access=[]))
    assert [v.code for v in info.value.violations] == ["docker_socket_not_declared"]
    assert info.value.violations[0].service == "agent"


def test_the_input_is_never_modified() -> None:
    compose = base_compose()
    before = copy.deepcopy(compose)
    rewrite(compose)
    assert compose == before


def test_changes_are_reported_for_the_audit_log() -> None:
    changes = rewrite(base_compose()).changes
    assert any("host ports removed" in c for c in changes)
    assert any("renamed" in c for c in changes)


def _mut(fn: Callable[[dict[str, Any]], None]) -> Callable[[dict[str, Any]], dict[str, Any]]:
    def apply(compose: dict[str, Any]) -> dict[str, Any]:
        fn(compose)
        return compose

    return apply


def _svc(compose: dict[str, Any]) -> dict[str, Any]:
    return compose["services"]["agent"]  # type: ignore[no-any-return]


ADVERSARIAL: list[tuple[str, Callable[[dict[str, Any]], None], str]] = [
    ("privileged", lambda c: _svc(c).update(privileged=True), "privileged"),
    ("host network", lambda c: _svc(c).update(network_mode="host"), "host_namespace"),
    (
        "another container's network",
        lambda c: _svc(c).update(network_mode="container:x"),
        "host_namespace",
    ),
    ("host pid", lambda c: _svc(c).update(pid="host"), "host_namespace"),
    ("host ipc", lambda c: _svc(c).update(ipc="host"), "host_namespace"),
    ("sys_admin", lambda c: _svc(c).update(cap_add=["SYS_ADMIN"]), "dangerous_capability"),
    ("all capabilities", lambda c: _svc(c).update(cap_add=["ALL"]), "dangerous_capability"),
    (
        "a device on a non-gpu module",
        lambda c: _svc(c).update(devices=["/dev/sda:/dev/sda"]),
        "device_not_allowed",
    ),
    (
        "bind mount of /etc",
        lambda c: _svc(c)["volumes"].append({"type": "bind", "source": "/etc", "target": "/e"}),
        "bind_outside_module",
    ),
    (
        "bind mount escaping with ..",
        lambda c: _svc(c)["volumes"].append(
            {"type": "bind", "source": f"{MODULE_DIR}/../other", "target": "/e"}
        ),
        "bind_outside_module",
    ),
    (
        "short-syntax bind of /",
        lambda c: _svc(c)["volumes"].append("/:/host"),
        "bind_outside_module",
    ),
    (
        "external volume",
        lambda c: c["volumes"].update(ext={"external": True, "name": "x"}),
        "external_volume",
    ),
    (
        "volume bound to the host through driver options",
        lambda c: c["volumes"].update(
            sneaky={
                "driver": "local",
                "driver_opts": {"type": "none", "o": "bind", "device": "/etc"},
            }
        ),
        "volume_bind_outside_module",
    ),
    (
        "external network",
        lambda c: c["networks"].update(other={"name": "elsewhere", "external": True}),
        "external_network",
    ),
    (
        "host network driver",
        lambda c: c["networks"].update(odd={"driver": "host"}),
        "network_driver",
    ),
    ("a build", lambda c: _svc(c).update(build={"context": "."}), "build_not_allowed"),
    (
        "an undeclared image",
        lambda c: _svc(c).update(image="evil/image:latest"),
        "image_not_declared",
    ),
    (
        "an env_file outside the module",
        lambda c: _svc(c).update(env_file=["/etc/shadow"]),
        "file_outside_module",
    ),
    (
        "a secret file outside the module",
        lambda c: c.update(secrets={"s": {"file": "/root/key"}}),
        "file_outside_module",
    ),
    ("an undeclared network", lambda c: _svc(c).update(networks={"nope": {}}), "unknown_network"),
    (
        "the shared network without declaring it",
        lambda c: _svc(c).update(networks={"core": {}}),
        "bus_not_declared",
    ),
    (
        "the reserved network key",
        lambda c: c["networks"].update(bus={"internal": True}),
        "reserved_name",
    ),
]


@pytest.mark.parametrize(
    ("mutation", "code"), [(a[1], a[2]) for a in ADVERSARIAL], ids=[a[0] for a in ADVERSARIAL]
)
def test_every_rule_rejects_its_violation(
    mutation: Callable[[dict[str, Any]], None], code: str
) -> None:
    compose = base_compose()
    mutation(compose)
    with pytest.raises(ComposeRejected) as info:
        rewrite(compose)
    assert code in {v.code for v in info.value.violations}


def test_a_gpu_module_may_use_gpu_devices_only() -> None:
    gpu = manifest(hardware={"gpu": "nvidia"})
    ok = base_compose()
    _svc(ok)["devices"] = ["/dev/nvidia0:/dev/nvidia0", {"source": "/dev/dri"}]
    rewrite(ok, manifest=gpu)
    bad = base_compose()
    _svc(bad)["devices"] = ["/dev/sda:/dev/sda"]
    with pytest.raises(ComposeRejected):
        rewrite(bad, manifest=gpu)


def test_all_violations_are_reported_together() -> None:
    compose = base_compose()
    _svc(compose).update(privileged=True, network_mode="host", build={"context": "."})
    with pytest.raises(ComposeRejected) as info:
        rewrite(compose)
    codes = {v.code for v in info.value.violations}
    assert {"privileged", "host_namespace", "build_not_allowed"} <= codes


def test_the_manifest_must_match_the_compose_file() -> None:
    with pytest.raises(ComposeRejected) as info:
        rewrite(
            base_compose(), manifest=manifest(web_ui={"service": "ghost", "port": 1, "path": "/x"})
        )
    codes = {v.code for v in info.value.violations}
    assert "unknown_service" in codes
    # the real web service now uses the shared network without declaring it
    assert "bus_not_declared" in codes


# --- property: two modules can never collide ---------------------------------------------------


def _resource_names(compose: dict[str, Any], aliases: dict[str, str]) -> set[str]:
    names = {compose["name"]}
    names |= {s["container_name"] for s in compose["services"].values()}
    names |= {v["name"] for v in compose.get("volumes", {}).values()}
    names |= {n["name"] for k, n in compose["networks"].items() if k != "bus"}
    names |= set(aliases.values())
    return names


@settings(max_examples=100, deadline=None, derandomize=True)
@given(
    services=st.lists(
        st.from_regex(r"^[a-z][a-z0-9-]{0,12}$", fullmatch=True),
        min_size=1,
        max_size=4,
        unique=True,
    ),
    ports=st.lists(st.integers(min_value=1, max_value=65535), max_size=3),
    volumes=st.lists(
        st.from_regex(r"^[a-z][a-z0-9]{0,8}$", fullmatch=True), max_size=3, unique=True
    ),
)
def test_two_modules_with_identical_compose_files_share_no_resource_name(
    services: list[str], ports: list[int], volumes: list[str]
) -> None:
    def build(module_id: str) -> tuple[dict[str, Any], dict[str, str]]:
        compose = {
            "services": {
                name: {
                    "image": SERVER_IMAGE,
                    "ports": [{"target": p, "published": str(p)} for p in ports],
                    "volumes": [
                        {"type": "volume", "source": v, "target": f"/{v}"} for v in volumes
                    ],
                    "networks": {"pack": {}},
                }
                for name in services
            },
            "networks": {"pack": {"name": "shared-name", "internal": True}},
            "volumes": {v: {"name": f"shared-{v}"} for v in volumes},
        }
        mf = manifest(
            id=module_id,
            web_ui={"service": services[0], "port": 80, "path": "/x"},
            host_access=[],
        )
        result = rewrite_compose(compose, mf, module_dir=f"/m/{module_id}")
        assert all("ports" not in s for s in result.compose["services"].values())
        return result.compose, dict(result.bus_aliases)

    first, second = build("aa-mod"), build("bb-mod")
    assert _resource_names(*first).isdisjoint(_resource_names(*second))
    for compose, _ in (first, second):
        for name in _resource_names(compose, {}) - {compose["name"]}:
            assert name.startswith("cobble-")
