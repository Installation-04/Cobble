"""Fetch the source of a tag and pack it as a Docker build context.

Credentials: the Forgejo token reaches `git` through GIT_ASKPASS (an environment variable of
that one process); it is never written to a git config, a remote URL or the build context
(`.git` is left out of the context).
"""

from __future__ import annotations

import asyncio
import os
import re
import stat
import tarfile
from pathlib import Path

from .config import Settings

_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,99}$")

ASKPASS = """#!/bin/sh
# Answers git's credential prompts from the environment (never from disk or the command line).
case "$1" in
  Username*) printf '%s\\n' "$COBBLE_GIT_USER" ;;
  *) printf '%s\\n' "$COBBLE_GIT_TOKEN" ;;
esac
"""


class SourceError(RuntimeError):
    """The source could not be fetched or packed. `code` is machine readable."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code


def valid_ref(ref: str) -> bool:
    return bool(_REF.match(ref)) and ".." not in ref and not ref.endswith(("/", ".lock", "."))


class Source:
    def __init__(self, settings: Settings) -> None:
        self._s = settings
        self._home = settings.data_dir / ".home"
        self._askpass = settings.data_dir / ".askpass.sh"

    def prepare(self) -> None:
        self._home.mkdir(parents=True, exist_ok=True)
        self._s.builds_dir.mkdir(parents=True, exist_ok=True)
        self._askpass.write_text(ASKPASS, "utf-8")
        self._askpass.chmod(stat.S_IRWXU)

    def resolve_url(self, url: str) -> str:
        """Apply the optional rewrite and enforce the allow-list: credentials only go to URLs
        under the configured git server."""
        s = self._s
        if s.git_rewrite_from and url.startswith(s.git_rewrite_from):
            url = s.git_rewrite_to + url[len(s.git_rewrite_from) :]
        if not url.startswith(s.forgejo_url.rstrip("/") + "/"):
            raise SourceError("repo_url_not_allowed")
        return url

    def _env(self) -> dict[str, str]:
        return {
            "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
            "HOME": str(self._home),
            "LC_ALL": "C",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_ALLOW_PROTOCOL": "http:https:file",
            "GIT_TEMPLATE_DIR": "",
            "GIT_ASKPASS": str(self._askpass),
            "COBBLE_GIT_USER": self._s.forgejo_user,
            "COBBLE_GIT_TOKEN": self._s.forgejo_token,
        }

    async def clone(self, url: str, ref: str, dest: Path, timeout: float = 300) -> None:  # noqa: ASYNC109
        if not valid_ref(ref):
            raise SourceError("bad_ref")
        proc = await asyncio.create_subprocess_exec(
            "git",
            "clone",
            "--quiet",
            "--depth",
            "1",
            "--no-tags",
            "--branch",
            ref,
            "--",
            self.resolve_url(url),
            str(dest),
            env=self._env(),
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            _out, err = await asyncio.wait_for(proc.communicate(), timeout)
        except TimeoutError:
            proc.kill()
            await proc.wait()
            raise SourceError("git_timeout") from None
        if proc.returncode != 0:
            detail = err.decode("utf-8", "replace").replace(self._s.forgejo_token, "***")
            raise SourceError("git_failed", detail.strip()[-300:])

    def pack(self, tree: Path, archive: Path) -> None:
        """Tar `tree` (without `.git`) into `archive`, refusing an oversized or Dockerfile-less
        context."""
        if not (tree / "Dockerfile").is_file():
            raise SourceError("no_dockerfile")
        limit = self._s.max_context_mb * 1024 * 1024
        total = 0
        with tarfile.open(archive, "w") as tar:
            for path in sorted(tree.rglob("*")):
                relative = path.relative_to(tree)
                if ".git" in relative.parts:
                    continue
                if path.is_symlink() or not (path.is_file() or path.is_dir()):
                    continue  # no symlinks in the context: nothing can point outside of it
                if path.is_file():
                    total += path.stat().st_size
                    if total > limit:
                        raise SourceError("context_too_large")
                tar.add(path, arcname=str(relative), recursive=False)
