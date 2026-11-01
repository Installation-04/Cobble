"""Publishes the routes of the running modules on the reverse proxy.

Validate-then-rename: every route file is written next to its final name, renamed into place,
and the proxy is asked to load the whole configuration. If the proxy refuses it, the previous
files are put back, so a bad route never stays on disk and the proxy keeps serving the last
good configuration (Caddy applies a configuration only if it loads).
"""

from __future__ import annotations

import logging
import os
import re
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Protocol

import httpx

from .runner import RunnerError

log = logging.getLogger(__name__)

_SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")


class Edge(Protocol):
    def sync(self, routes: Mapping[str, str]) -> None:
        """Make the published routes exactly `routes` (module id -> snippet)."""


class NullEdge:
    """No proxy to configure (tests, or a module-manager started without one)."""

    def sync(self, routes: Mapping[str, str]) -> None:
        return None


Reload = Callable[[str], None]


def caddy_reload(admin_socket: Path, timeout_s: float = 10.0) -> Reload:
    """Loads a Caddyfile through Caddy's admin API on a unix socket."""

    def reload(caddyfile: str) -> None:
        transport = httpx.HTTPTransport(uds=str(admin_socket))
        try:
            with httpx.Client(transport=transport, timeout=timeout_s) as client:
                response = client.post(
                    "http://caddy/load",
                    content=caddyfile.encode(),
                    headers={"Content-Type": "text/caddyfile"},
                )
        except httpx.HTTPError:
            raise RunnerError("route_failed") from None
        if response.status_code != 200:
            # The body names the offending directive, never a secret; it is not logged here
            # because nothing in a route can be one, but it is kept out of the error code.
            raise RunnerError("route_failed")

    return reload


class CaddyEdge:
    def __init__(self, routes_dir: Path, caddyfile: Path, reload: Reload) -> None:
        self._dir = routes_dir
        self._caddyfile = caddyfile
        self._reload = reload

    def _current(self) -> dict[str, str]:
        found: dict[str, str] = {}
        if self._dir.is_dir():
            for path in self._dir.glob("*.caddy"):
                found[path.stem] = path.read_text()
        return found

    def sync(self, routes: Mapping[str, str]) -> None:
        for module_id in routes:
            if not _SAFE_ID.match(module_id):
                raise RunnerError("route_failed")
        self._dir.mkdir(parents=True, exist_ok=True)
        before = self._current()
        if dict(routes) == before:
            return
        self._write(routes, before)
        try:
            self._reload(self._caddyfile.read_text())
        except Exception:
            self._write(before, routes)  # put the last good state back
            raise

    def _write(self, wanted: Mapping[str, str], present: Mapping[str, str]) -> None:
        for module_id, text in wanted.items():
            if present.get(module_id) == text:
                continue
            final = self._dir / f"{module_id}.caddy"
            temp = self._dir / f".{module_id}.caddy.tmp"
            temp.write_text(text)
            os.replace(temp, final)
        for module_id in present:
            if module_id not in wanted:
                (self._dir / f"{module_id}.caddy").unlink(missing_ok=True)
