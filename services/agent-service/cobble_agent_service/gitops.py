"""Git operations of agent-service.

Credentials: the Forgejo service token is read from agent-service's own environment and handed
to `git` only for the commands that talk to Forgejo (clone, push), through GIT_ASKPASS. It is
never written to a git config, a remote URL, a worktree, or the agent container.

Trust: the worktree is writable by the agent, so its `.git` directory is untrusted (hooks,
`core.fsmonitor`, `credential.helper`, ... could execute code in this privileged process).
agent-service therefore never runs git inside the worktree. It keeps its own bare clone
(`repo.git`), and after the run it only *fetches* refs from the worktree into that clean
repository (fetch from a local path reads objects and refs; it executes no repository code),
then inspects and pushes from there.
"""

from __future__ import annotations

import asyncio
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path

from .config import Settings

RESULT_REF = "refs/cobble/result"
_SHA = re.compile(r"^[0-9a-f]{40,64}$")


class GitError(RuntimeError):
    """A git command failed. The message never contains credentials."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class Collected:
    head_sha: str
    commits: int
    diff_stat: str


ASKPASS = """#!/bin/sh
# Answers git's credential prompts from the environment (never from disk or the command line).
case "$1" in
  Username*) printf '%s\\n' "$COBBLE_GIT_USER" ;;
  *) printf '%s\\n' "$COBBLE_GIT_TOKEN" ;;
esac
"""


class GitOps:
    def __init__(self, settings: Settings) -> None:
        self._s = settings
        self._home = settings.data_dir / ".home"
        self._askpass = settings.data_dir / ".askpass.sh"

    def prepare_environment(self) -> None:
        self._home.mkdir(parents=True, exist_ok=True)
        self._s.runs_dir.mkdir(parents=True, exist_ok=True)
        self._askpass.write_text(ASKPASS, "utf-8")
        self._askpass.chmod(stat.S_IRWXU)

    # --- URL handling -------------------------------------------------------------------

    def resolve_url(self, url: str) -> str:
        """Apply the optional rewrite (public URL -> internal URL) and enforce the allow-list.

        Credentials only ever go to URLs under the configured Forgejo URL."""
        s = self._s
        if s.git_rewrite_from and url.startswith(s.git_rewrite_from):
            url = s.git_rewrite_to + url[len(s.git_rewrite_from) :]
        base = s.forgejo_url.rstrip("/") + "/"
        if not url.startswith(base):
            raise GitError("repo_url_not_allowed")
        return url

    # --- plumbing -----------------------------------------------------------------------

    def _env(self, *, auth: bool) -> dict[str, str]:
        env = {
            "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
            "HOME": str(self._home),
            "LC_ALL": "C",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_ALLOW_PROTOCOL": "http:https:file",
            "GIT_TEMPLATE_DIR": "",
        }
        if auth:
            env.update(
                GIT_ASKPASS=str(self._askpass),
                COBBLE_GIT_USER=self._s.forgejo_user,
                COBBLE_GIT_TOKEN=self._s.forgejo_token,
            )
        return env

    async def _git(
        self,
        *args: str,
        cwd: Path | None = None,
        auth: bool = False,
        timeout: float = 300,  # noqa: ASYNC109
    ) -> str:
        proc = await asyncio.create_subprocess_exec(
            "git",
            *args,
            cwd=cwd,
            env=self._env(auth=auth),
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout)
        except TimeoutError:
            proc.kill()
            await proc.wait()
            raise GitError("git_timeout", args[0]) from None
        if proc.returncode != 0:
            detail = err.decode("utf-8", errors="replace").strip()[-500:]
            raise GitError("git_failed", f"git {args[0]}: {detail}")
        return out.decode("utf-8", errors="replace").strip()

    # --- run lifecycle ------------------------------------------------------------------

    async def prepare_workspace(
        self,
        run_dir: Path,
        url: str,
        base_branch: str,
        branch: str,
        instructions: str,
    ) -> str:
        """Clone, create the task branch and write the instructions. Returns the base sha."""
        bare = run_dir / "repo.git"
        work = run_dir / "work"
        await self._git("clone", "--bare", "--no-tags", "--quiet", url, str(bare), auth=True)
        try:
            base_sha = await self._git(
                "rev-parse", "--verify", f"refs/heads/{base_branch}^{{commit}}", cwd=bare
            )
        except GitError:
            raise GitError("base_branch_missing", base_branch) from None
        # Continue an existing task branch (a retry after a red CI), otherwise start from base.
        try:
            start_sha = await self._git(
                "rev-parse", "--verify", f"refs/heads/{branch}^{{commit}}", cwd=bare
            )
        except GitError:
            start_sha = base_sha
        await self._git("clone", "--quiet", "--no-hardlinks", "--no-checkout", str(bare), str(work))
        await self._git("checkout", "--quiet", "-B", branch, start_sha, cwd=work)
        await self._git("remote", "set-url", "origin", url, cwd=work)
        for key, value in (
            ("user.name", "Cobble Agent"),
            ("user.email", "agent@cobble.local"),
            ("gc.auto", "0"),
        ):
            await self._git("config", key, value, cwd=work)
        exclude = work / ".git" / "info" / "exclude"
        exclude.parent.mkdir(parents=True, exist_ok=True)
        with exclude.open("a", encoding="utf-8") as fh:
            fh.write(".cobble/\n.aider*\n.venv/\nnode_modules/\n__pycache__/\n")
        cobble = work / ".cobble"
        cobble.mkdir(exist_ok=True)
        (cobble / "instructions.md").write_text(instructions, "utf-8")
        return start_sha

    async def collect(self, run_dir: Path, branch: str, base_sha: str) -> Collected:
        """Fetch the agent's branch into the trusted repository and describe it."""
        bare = run_dir / "repo.git"
        work_git = run_dir / "work" / ".git"
        try:
            await self._git(
                "-c",
                "transfer.fsckObjects=true",
                "fetch",
                "--quiet",
                "--no-tags",
                "--no-write-fetch-head",
                "--no-recurse-submodules",
                str(work_git),
                f"+refs/heads/{branch}:{RESULT_REF}",
                cwd=bare,
            )
        except GitError:
            raise GitError("branch_missing", branch) from None
        head = await self._git("rev-parse", "--verify", f"{RESULT_REF}^{{commit}}", cwd=bare)
        if not _SHA.match(head):
            raise GitError("bad_head")
        try:
            await self._git("merge-base", "--is-ancestor", base_sha, head, cwd=bare)
        except GitError:
            raise GitError("history_rewritten") from None
        commits = int(await self._git("rev-list", "--count", f"{base_sha}..{head}", cwd=bare))
        stat_out = await self._git("diff", "--stat", "--no-color", base_sha, head, cwd=bare)
        return Collected(head, commits, stat_out[-2000:])

    async def push(self, run_dir: Path, branch: str) -> None:
        bare = run_dir / "repo.git"
        await self._git(
            "push", "--quiet", "origin", f"{RESULT_REF}:refs/heads/{branch}", cwd=bare, auth=True
        )
