"""How the module-manager talks to Docker, behind a small interface.

`Runner` is what the lifecycle needs; `ComposeRunner` implements it with `docker compose` and
`FakeRunner` records calls and injects failures for tests. Hooks print nothing that is kept
except `::secret::KEY=VALUE` lines, which become secrets of the module that ran the hook.
"""

from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

SECRET_PREFIX = "::secret::"  # noqa: S105 - a line marker in hook output, not a credential


class RunnerError(Exception):
    """A Docker or hook failure. `code` is stable and safe to log; no output is attached."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class SimulatedCrash(BaseException):
    """Tests only: the manager process dies here (nothing in the lifecycle may catch it)."""


@dataclass(frozen=True)
class HookResult:
    returncode: int
    produced_secrets: Mapping[str, str] = field(default_factory=dict)


class Runner(Protocol):
    def up(self, project: str, compose: Mapping[str, Any], env: Mapping[str, str]) -> None: ...

    def down(self, project: str, *, volumes: bool) -> None: ...

    def wait_healthy(self, project: str, timeout_s: float) -> bool: ...

    def run_hook(self, script: str, env: Mapping[str, str]) -> HookResult: ...


# What a hook may inherit from the module-manager. Nothing else: the manager's own settings hold
# the database and Redis passwords, its API token and more, none of which a hook needs.
HOOK_ENV_ALLOWLIST = ("PATH", "HOME", "LANG", "LC_ALL", "TZ", "DOCKER_CONFIG", "DOCKER_HOST")


def _hook_base_env() -> dict[str, str]:
    return {key: os.environ[key] for key in HOOK_ENV_ALLOWLIST if key in os.environ}


def parse_hook_output(stdout: str) -> dict[str, str]:
    """Only `::secret::KEY=VALUE` lines are kept; everything else is dropped."""
    secrets: dict[str, str] = {}
    for line in stdout.splitlines():
        if line.startswith(SECRET_PREFIX) and "=" in line:
            key, _, value = line.removeprefix(SECRET_PREFIX).partition("=")
            if key and value:
                secrets[key.strip()] = value
    return secrets


class ComposeRunner:
    """`docker compose` through the CLI. The compose file is piped on stdin, never written."""

    def __init__(self, docker: str = "docker", hook_timeout_s: float = 600.0) -> None:
        self._docker = docker
        self._hook_timeout_s = hook_timeout_s

    def _run(
        self, args: list[str], *, stdin: str | None = None, env: Mapping[str, str] | None = None
    ) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(  # noqa: S603 - fixed argv, no shell
                [self._docker, *args],
                input=stdin,
                env={**os.environ, **(env or {})},
                capture_output=True,
                text=True,
                timeout=600,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            raise RunnerError("docker_unavailable") from None

    def up(self, project: str, compose: Mapping[str, Any], env: Mapping[str, str]) -> None:
        result = self._run(
            ["compose", "-p", project, "-f", "-", "up", "-d", "--wait", "--no-build"],
            stdin=json.dumps(compose),
            env=env,
        )
        if result.returncode != 0:
            raise RunnerError("up_failed")

    def render(
        self,
        module_dir: str,
        compose_file: str,
        env: Mapping[str, str],
        variant: str | None = None,
    ) -> dict[str, Any]:
        """`docker compose config --format json` of a module (variables resolved with `env`)."""
        args = ["compose", "--project-directory", module_dir, "-f", f"{module_dir}/{compose_file}"]
        if variant:
            args += ["--profile", variant]
        result = self._run(
            [*args, "config", "--format", "json"], env={**env, "COBBLE_VARIANT": variant or ""}
        )
        if result.returncode != 0:
            raise RunnerError("render_failed")
        try:
            rendered = json.loads(result.stdout)
        except json.JSONDecodeError:
            raise RunnerError("render_failed") from None
        if not isinstance(rendered, dict):
            raise RunnerError("render_failed")
        return rendered

    def down(self, project: str, *, volumes: bool) -> None:
        args = ["compose", "-p", project, "down", "--remove-orphans"]
        if volumes:
            args.append("--volumes")
        if self._run(args).returncode != 0:
            raise RunnerError("down_failed")

    def wait_healthy(self, project: str, timeout_s: float) -> bool:
        result = self._run(["compose", "-p", project, "ps", "--format", "json"])
        if result.returncode != 0:
            return False
        rows = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]

        # A one-shot job (an init container) that finished successfully is done, not unhealthy.
        def ready(row: dict[str, Any]) -> bool:
            if row.get("State") == "exited" and row.get("ExitCode", 1) == 0:
                return True
            return row.get("State") == "running" and row.get("Health", "") in ("", "healthy")

        return bool(rows) and all(ready(row) for row in rows)

    def run_hook(self, script: str, env: Mapping[str, str]) -> HookResult:
        try:
            result = subprocess.run(  # noqa: S603 - the script path comes from the catalogue
                ["bash", script],  # noqa: S607
                env={**_hook_base_env(), **env},
                capture_output=True,
                text=True,
                timeout=self._hook_timeout_s,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return HookResult(returncode=124)
        return HookResult(result.returncode, parse_hook_output(result.stdout))


@dataclass
class FakeRunner:
    """In-memory runner for tests: records everything, fails or crashes where told to.

    `fail` / `crash` hold `(operation, name)` pairs: `("up", "cobble-demo")`,
    `("down", project)`, `("health", project)`, `("hook", script)`.
    """

    running: dict[str, Mapping[str, Any]] = field(default_factory=dict)
    volumes: set[str] = field(default_factory=set)
    calls: list[tuple[str, str]] = field(default_factory=list)
    hook_envs: list[tuple[str, dict[str, str]]] = field(default_factory=list)
    fail: set[tuple[str, str]] = field(default_factory=set)
    crash: set[tuple[str, str]] = field(default_factory=set)
    hook_exit: dict[str, int] = field(default_factory=dict)
    hook_secrets: dict[str, dict[str, str]] = field(default_factory=dict)

    def _check(self, operation: str, name: str) -> None:
        self.calls.append((operation, name))
        if (operation, name) in self.crash:
            raise SimulatedCrash
        if (operation, name) in self.fail:
            raise RunnerError(f"{operation}_failed")

    def up(self, project: str, compose: Mapping[str, Any], env: Mapping[str, str]) -> None:
        self._check("up", project)
        self.running[project] = compose
        self.volumes.add(project)

    def down(self, project: str, *, volumes: bool) -> None:
        self._check("down", project)
        self.running.pop(project, None)
        if volumes:
            self.volumes.discard(project)

    def wait_healthy(self, project: str, timeout_s: float) -> bool:
        self.calls.append(("health", project))
        if ("health", project) in self.crash:
            raise SimulatedCrash
        return ("health", project) not in self.fail

    def run_hook(self, script: str, env: Mapping[str, str]) -> HookResult:
        self.calls.append(("hook", script))
        self.hook_envs.append((script, dict(env)))
        if ("hook", script) in self.crash:
            raise SimulatedCrash
        code = self.hook_exit.get(script, 1 if ("hook", script) in self.fail else 0)
        return HookResult(code, dict(self.hook_secrets.get(script, {})))
