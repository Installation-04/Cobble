"""The platform's anti-conflict rules, applied to a module's compose file (PLAN.md section 6).

The input is what `docker compose config --format json` prints (a plain mapping, so this module
needs neither Docker nor a daemon). The module-manager applies these rules; a manifest can only
*declare* what it needs (`host_access`, `web_ui`, `bus`), never switch a rule off.

Rewritten:   host ports removed; the project, container, volume and network names namespaced
             `cobble-<id>…`; a shared-network attachment (with a unique alias) only for the
             services that declared one; default CPU, memory and PID limits; labels; restart policy.
Rejected:    privileged mode, host namespaces, dangerous capabilities, devices on non-GPU modules,
             bind mounts outside the module directory (the Docker socket only when declared),
             external volumes and networks, `build:` and images the manifest does not list,
             file references that leave the module directory.
All defects are collected and reported together, so an author fixes them in one pass.
"""

from __future__ import annotations

import copy
import posixpath
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from .manifest import Manifest

DOCKER_SOCKET = "/var/run/docker.sock"
BUS_KEY = "bus"
_DANGEROUS_CAPS = {"ALL", "SYS_ADMIN"}
_BAD_NETWORK_DRIVERS = {"host", "macvlan", "ipvlan"}
_GPU_DEVICE_PREFIXES = ("/dev/dri", "/dev/kfd", "/dev/nvidia", "/dev/nvidiactl", "/dev/nvidia-")


@dataclass(frozen=True)
class Violation:
    code: str
    service: str | None
    detail: str


class ComposeRejected(ValueError):
    def __init__(self, violations: list[Violation]) -> None:
        super().__init__(
            "; ".join(f"{v.service or '<file>'}: {v.code} ({v.detail})" for v in violations)
        )
        self.violations = tuple(violations)


@dataclass(frozen=True)
class Limits:
    """Defaults applied only where the module did not set its own."""

    cpus: float = 1.0
    memory_bytes: int = 1024 * 1024 * 1024
    pids: int = 512


@dataclass(frozen=True)
class RewriteResult:
    compose: dict[str, Any]
    bus_aliases: Mapping[str, str]
    changes: tuple[str, ...] = field(default_factory=tuple)


def _inside(path: str, directory: str) -> bool:
    if not path.startswith("/"):
        return False
    normalized = posixpath.normpath(path)
    base = posixpath.normpath(directory)
    return normalized == base or normalized.startswith(base + "/")


def _gpu_capable(manifest: Manifest) -> bool:
    return manifest.hardware.gpu != "none" or any(v.gpu != "none" for v in manifest.variants)


def _device_path(device: Any) -> str:
    if isinstance(device, str):
        return device.split(":", 1)[0]
    if isinstance(device, Mapping):
        return str(device.get("source", ""))
    return ""


def rewrite_compose(
    compose: Mapping[str, Any],
    manifest: Manifest,
    *,
    module_dir: str,
    bus_network: str = "cobble_core",
    limits: Limits | None = None,
) -> RewriteResult:
    """Apply the platform rules; raise `ComposeRejected` listing every violation."""
    limits = limits or Limits()
    module = manifest.id
    prefix = f"cobble-{module}"
    source: dict[str, Any] = copy.deepcopy(dict(compose))
    services: dict[str, Any] = source.get("services") or {}
    violations: list[Violation] = []
    changes: list[str] = []

    def violate(code: str, service: str | None, detail: str) -> None:
        violations.append(Violation(code, service, detail))

    # --- which services join the shared network
    bus_services: set[str] = set(manifest.bus)
    if manifest.web_ui is not None:
        bus_services.add(manifest.web_ui.service)
    for name in sorted(bus_services - set(services)):
        violate(
            "unknown_service", name, "declared in the manifest but absent from the compose file"
        )

    # --- top-level networks
    top_networks: dict[str, Any] = source.get("networks") or {}
    bus_keys: set[str] = set()
    new_networks: dict[str, Any] = {}
    for key, cfg in sorted(top_networks.items()):
        cfg = cfg or {}
        if key == BUS_KEY and not (cfg.get("external") and cfg.get("name") == bus_network):
            violate("reserved_name", None, f"network key {BUS_KEY!r} is reserved")
            continue
        if cfg.get("external"):
            if cfg.get("name") == bus_network:
                bus_keys.add(key)
            else:
                violate("external_network", None, f"network {key!r} is external")
            continue
        if cfg.get("driver") in _BAD_NETWORK_DRIVERS:
            violate("network_driver", None, f"network {key!r} uses driver {cfg.get('driver')!r}")
            continue
        renamed = {**cfg, "name": f"{prefix}-{key}"}
        new_networks[key] = renamed
        changes.append(f"network {key!r} renamed to {renamed['name']!r}")

    # --- top-level volumes
    new_volumes: dict[str, Any] = {}
    for key, cfg in sorted((source.get("volumes") or {}).items()):
        cfg = cfg or {}
        if cfg.get("external"):
            violate("external_volume", None, f"volume {key!r} is external")
            continue
        options = cfg.get("driver_opts") or {}
        if "bind" in str(options.get("o", "")) and not _inside(
            str(options.get("device", "")), module_dir
        ):
            violate(
                "volume_bind_outside_module",
                None,
                f"volume {key!r} binds {options.get('device')!r}",
            )
            continue
        new_volumes[key] = {**cfg, "name": f"{prefix}-{key}"}
        changes.append(f"volume {key!r} renamed to {prefix}-{key!r}")

    # --- top-level file references
    for section in ("configs", "secrets"):
        for key, cfg in (source.get(section) or {}).items():
            path = (cfg or {}).get("file")
            if path is not None and not _inside(str(path), module_dir):
                violate("file_outside_module", None, f"{section[:-1]} {key!r} reads {path!r}")

    # --- services
    bus_aliases: dict[str, str] = {}
    needs_default_network = False
    for name in sorted(services):
        svc: dict[str, Any] = services[name] or {}
        services[name] = svc

        if svc.get("build") is not None:
            violate("build_not_allowed", name, "images must be published and pinned by digest")
        image = svc.get("image")
        if image is not None and image not in manifest.images:
            violate("image_not_declared", name, f"{image!r} is not listed in the manifest images")
        if svc.get("privileged"):
            violate("privileged", name, "privileged containers are forbidden")
        mode = str(svc.get("network_mode") or "")
        if mode == "host" or mode.startswith("container:"):
            violate("host_namespace", name, f"network_mode {mode!r}")
        for key in ("pid", "ipc", "uts", "userns_mode"):
            if svc.get(key) == "host":
                violate("host_namespace", name, f"{key}: host")
        for capability in svc.get("cap_add") or []:
            if str(capability).upper().removeprefix("CAP_") in _DANGEROUS_CAPS:
                violate("dangerous_capability", name, f"cap_add {capability}")
        for device in svc.get("devices") or []:
            device_path = _device_path(device)
            if not (_gpu_capable(manifest) and device_path.startswith(_GPU_DEVICE_PREFIXES)):
                violate("device_not_allowed", name, f"device {device_path!r}")

        for volume in svc.get("volumes") or []:
            if isinstance(volume, str):
                head = volume.split(":", 1)[0]
                is_bind = head.startswith(("/", "."))
                src = head
            else:
                is_bind = volume.get("type") == "bind"
                src = str(volume.get("source", ""))
            if not is_bind:
                continue
            if src == DOCKER_SOCKET:
                if "docker_socket" not in manifest.host_access:
                    violate("docker_socket_not_declared", name, "add host_access: [docker_socket]")
            elif not _inside(src, module_dir):
                violate("bind_outside_module", name, f"bind mount of {src!r}")

        env_files = svc.get("env_file") or []
        if isinstance(env_files, (str, Mapping)):
            env_files = [env_files]
        for entry in env_files:
            path = entry.get("path") if isinstance(entry, Mapping) else entry
            if path is not None and not _inside(str(path), module_dir):
                violate("file_outside_module", name, f"env_file {path!r}")

        # network attachments
        declared = svc.get("networks")
        attachments: dict[str, Any]
        if isinstance(declared, list):
            attachments = {n: {} for n in declared}
        else:
            attachments = {k: (v or {}) for k, v in (declared or {}).items()}
        wants_bus = False
        for key in list(attachments):
            if key in bus_keys:
                del attachments[key]
                wants_bus = True
            elif key not in new_networks and key != "default":
                violate("unknown_network", name, f"service uses undeclared network {key!r}")
        if wants_bus and name not in bus_services:
            violate("bus_not_declared", name, "add the service to `bus` or `web_ui.service`")
        if name in bus_services:
            alias = f"{prefix}-{name}"
            bus_aliases[name] = alias
            if declared is None and not attachments:
                attachments["default"] = {}
            attachments[BUS_KEY] = {"aliases": [alias]}
            changes.append(f"service {name!r} joins the shared network as {alias!r}")
        if "default" in attachments:
            needs_default_network = True
        if declared is not None or name in bus_services:
            svc["networks"] = attachments

        # rewrites
        if svc.get("ports"):
            changes.append(f"service {name!r}: host ports removed")
        svc.pop("ports", None)
        svc["container_name"] = f"{prefix}-{name}"
        labels = svc.get("labels") or {}
        if isinstance(labels, list):
            labels = dict(item.split("=", 1) if "=" in item else (item, "") for item in labels)
        labels.update({"cobble.managed": "true", "cobble.module": module, "cobble.service": name})
        svc["labels"] = labels
        svc.setdefault("restart", "unless-stopped")
        limit_keys = set(((svc.get("deploy") or {}).get("resources") or {}).get("limits") or {})
        if "mem_limit" not in svc and "memory" not in limit_keys:
            svc["mem_limit"] = limits.memory_bytes
        if "cpus" not in svc and "cpus" not in limit_keys:
            svc["cpus"] = limits.cpus
        if "pids_limit" not in svc and "pids" not in limit_keys:
            svc["pids_limit"] = limits.pids

    if violations:
        raise ComposeRejected(violations)

    if needs_default_network:
        new_networks["default"] = {"name": f"{prefix}_default"}
    if bus_aliases:
        new_networks[BUS_KEY] = {"name": bus_network, "external": True}
    source["name"] = prefix
    source["services"] = services
    source["networks"] = new_networks
    if new_volumes or "volumes" in source:
        source["volumes"] = new_volumes
    return RewriteResult(source, bus_aliases, tuple(changes))
