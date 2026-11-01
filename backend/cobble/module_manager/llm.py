"""Keeps the language-model gateway's model list in step with the installed backends.

Modules that provide `llm-backend` say which models they serve (manifest `llm`). The platform
writes them to a file the gateway includes, and restarts the gateway (the spike showed a restart
is the supported way to load a changed list: about 20 seconds). If the gateway does not come back
the previous list is put back, so a bad list never stays.
"""

from __future__ import annotations

import logging
import os
import subprocess
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

import yaml

from .runner import RunnerError

log = logging.getLogger(__name__)

EMPTY = "model_list: []\n"


@dataclass(frozen=True)
class LlmEntry:
    name: str  # what clients ask the gateway for
    model: str  # the gateway's own model string (provider/model)
    api_base: str | None = None  # where the backend listens (None: the provider's own address)
    # The key of a paid service. Never printed (repr hidden) and never logged.
    api_key: str | None = field(default=None, repr=False)
    # A model served on this machine costs nothing; a paid service is priced by the gateway.
    local: bool = True


def render_models(entries: Sequence[LlmEntry]) -> str:
    """The include file: one deployment per entry.

    It may hold API keys, so it is only ever in a volume that the module-manager writes and the
    gateway reads (no other container mounts it); it is never logged or sent anywhere.
    """
    if not entries:
        return EMPTY
    models = []
    for entry in sorted(entries, key=lambda e: (e.name, e.api_base or "", e.model)):
        params: dict[str, object] = {"model": entry.model}
        if entry.api_base is not None:
            params["api_base"] = entry.api_base
        if entry.api_key is not None:
            params["api_key"] = entry.api_key
        if entry.local:
            params["input_cost_per_token"] = 0
            params["output_cost_per_token"] = 0
        models.append({"model_name": entry.name, "litellm_params": params})
    return yaml.safe_dump({"model_list": models}, sort_keys=False)


class LlmGateway(Protocol):
    def sync(self, entries: Sequence[LlmEntry]) -> None:
        """Make the gateway serve exactly `entries` (plus its own static models)."""


class NullGateway:
    """No gateway to configure (tests, or a manager started without one)."""

    def sync(self, entries: Sequence[LlmEntry]) -> None:
        return None


class FileGateway:
    """Writes the include file, then restarts the gateway and waits for it to be live."""

    def __init__(
        self, path: Path, restart: Callable[[], None], wait_live: Callable[[], bool]
    ) -> None:
        self._path = path
        self._restart = restart
        self._wait_live = wait_live

    def _current(self) -> str:
        try:
            return self._path.read_text()
        except OSError:
            return EMPTY

    def _write(self, text: str) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temp = self._path.with_name(f".{self._path.name}.tmp")
        temp.write_text(text)
        # The gateway's user is not ours and the volume is shared with nothing else: readable by
        # it, writable only by us.
        temp.chmod(0o644)
        os.replace(temp, self._path)

    def sync(self, entries: Sequence[LlmEntry]) -> None:
        wanted = render_models(entries)
        before = self._current()
        if wanted == before and self._path.exists():
            return
        self._write(wanted)
        try:
            self._restart()
            if not self._wait_live():
                raise RunnerError("llm_failed")
        except Exception:
            self._write(before)  # the gateway did not take the list: put the last good one back
            try:
                self._restart()
                self._wait_live()
            except Exception:
                log.error("the language-model gateway could not be restarted after a rollback")
            raise


def docker_gateway(
    path: Path,
    *,
    docker: str = "docker",
    service: str = "litellm",
    network: str = "cobble_core",
    live_timeout_s: float = 180.0,
) -> FileGateway:
    """The gateway is the compose service `service` on the shared network."""

    def container() -> str:
        result = subprocess.run(  # noqa: S603 - fixed argv
            [
                docker,
                "ps",
                "-q",
                "--filter",
                f"label=com.docker.compose.service={service}",
                "--filter",
                f"network={network}",
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        ids = result.stdout.split()
        if result.returncode != 0 or len(ids) != 1:
            raise RunnerError("llm_failed")  # none, or more than one: never guess
        return ids[0]

    def restart() -> None:
        done = subprocess.run(  # noqa: S603
            [docker, "restart", container()],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        if done.returncode != 0:
            raise RunnerError("llm_failed")

    def wait_live() -> bool:
        deadline = time.monotonic() + live_timeout_s
        while time.monotonic() < deadline:
            try:
                state = subprocess.run(  # noqa: S603
                    [docker, "inspect", "-f", "{{.State.Health.Status}}", container()],
                    capture_output=True,
                    text=True,
                    timeout=30,
                    check=False,
                ).stdout.strip()
            except (OSError, subprocess.TimeoutExpired, RunnerError):
                state = ""
            if state == "healthy":
                return True
            time.sleep(2)
        return False

    return FileGateway(path, restart, wait_live)
