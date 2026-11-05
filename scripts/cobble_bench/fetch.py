"""Getting the generated code out of a finished (or stopped) bench project.

The API deliberately exposes no source files, so the bench reads the project's git repository
the way any developer would: a shallow `git clone`. The repository is named by the platform
as `<slug(project name)>-<first 6 hex digits of the project id>`. The token travels in the
environment of the `git` process (never in its arguments or in the logs).
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .projects import ReferenceProject
from .runner import slug


class FetchError(RuntimeError):
    """The generated code could not be retrieved."""


class GitFetcher:
    def __init__(
        self, url_template: str, token: str | None = None, *, timeout_s: int = 300
    ) -> None:
        if "{repo}" not in url_template:
            raise FetchError("the git URL template must contain {repo}")
        self.url_template, self.token, self.timeout_s = url_template, token, timeout_s

    def repo_name(self, api_project: dict[str, Any]) -> str:
        return f"{slug(api_project['name'])}-{str(api_project['id']).replace('-', '').lower()[:6]}"

    def fetch(self, project: ReferenceProject, api_project: dict[str, Any], dest: Path) -> Path:
        url = self.url_template.format(repo=self.repo_name(api_project))
        env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
        if self.token:
            env.update(
                GIT_CONFIG_COUNT="1",
                GIT_CONFIG_KEY_0="http.extraHeader",
                GIT_CONFIG_VALUE_0=f"Authorization: token {self.token}",
            )
        try:
            done = subprocess.run(  # noqa: S603
                ["git", "clone", "--quiet", "--depth", "1", url, str(dest)],  # noqa: S607
                env=env,
                capture_output=True,
                text=True,
                timeout=self.timeout_s,
                check=False,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
            raise FetchError(type(exc).__name__) from exc
        if done.returncode != 0:
            # git's message can echo the URL: keep only its last line, without the token.
            last = (done.stderr.strip().splitlines() or ["git clone failed"])[-1]
            raise FetchError(last.replace(self.token or "\0", "***")[:200])
        return dest


class DirFetcher:
    """Code already on disk: `<base>/<reference project name>/` (offline checks, saved trees)."""

    def __init__(self, base: Path) -> None:
        self.base = base

    def fetch(self, project: ReferenceProject, api_project: dict[str, Any], dest: Path) -> Path:
        source = self.base / project.name
        if not source.is_dir():
            raise FetchError(f"no code directory for {project.name}")
        shutil.copytree(source, dest)
        return dest
