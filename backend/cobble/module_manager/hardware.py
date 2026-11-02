"""What this machine offers, for choosing module variants (see `cobble_sdk.Hardware`)."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from cobble_sdk import Hardware

HostGpu = Literal["none", "nvidia", "amd"]


def read_ram_mb(meminfo: Path = Path("/proc/meminfo")) -> int:
    """Total RAM in MiB from /proc/meminfo; 0 when it cannot be read."""
    try:
        for line in meminfo.read_text("utf-8").splitlines():
            if line.startswith("MemTotal:"):
                return int(line.split()[1]) // 1024
    except (OSError, ValueError, IndexError):
        return 0
    return 0


def detect_gpu(dev: Path = Path("/dev"), proc: Path = Path("/proc")) -> HostGpu:
    """Best effort from inside a container: device nodes the host maps in, or the driver tree.

    The installer's own detection (written to the settings) wins; this is the fallback.
    """
    if (dev / "nvidiactl").exists() or (proc / "driver" / "nvidia").exists():
        return "nvidia"
    if (dev / "kfd").exists() and (dev / "dri").exists():
        return "amd"
    return "none"


def host_hardware(
    ram_mb: int = 0,
    gpu: str = "auto",
    *,
    meminfo: Path = Path("/proc/meminfo"),
    dev: Path = Path("/dev"),
    proc: Path = Path("/proc"),
) -> Hardware:
    """Settings first, detection for whatever is left on automatic."""
    detected_gpu: HostGpu = detect_gpu(dev, proc) if gpu == "auto" else gpu  # type: ignore[assignment]
    return Hardware(ram_mb=ram_mb or read_ram_mb(meminfo), gpu=detected_gpu)
