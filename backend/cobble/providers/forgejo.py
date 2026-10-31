"""GitProvider backed by Forgejo (the git server of the v0.1 pack).

Product names are allowed here (and only in `cobble/providers/`): the core talks to the
`GitProvider` protocol.
"""

from __future__ import annotations

import base64
import fnmatch
import os
import re
import shutil
import subprocess
import tempfile
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

from cobble.capabilities import CIProvider, CIState, MergeRefused, MergeRequestRef, RepoRef
from cobble.capabilities.git import TagExists, cap_diff

from .errors import ProviderConflict, ProviderError, ProviderNotFound
from .http import Api
from .settings import PackSettings

_REPO_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
_PLACEHOLDER = re.compile(r"\{\{\s*project_name\s*\}\}")
_SKIP_DIRS = {".git", "node_modules", ".venv", "__pycache__", ".pytest_cache", ".ruff_cache"}
# Statuses of a merge attempt that mean "the rules do not allow it" rather than "broken".
_MERGE_REFUSED_STATUSES = {403, 405, 409, 422}
MERGE_ATTEMPTS = 4  # a refusal while the server recomputes mergeability is retried
MERGE_RETRY_DELAY_S = 2.0
_TAG_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")


class ProviderTagExists(ProviderConflict, TagExists):
    """`tag` found the tag already there."""


def render_template(template_dir: Path, dest: Path, project_name: str) -> None:
    """Copy `template_dir` to `dest`, replacing `{{project_name}}` in text files."""
    for source in sorted(template_dir.rglob("*")):
        relative = source.relative_to(template_dir)
        if _SKIP_DIRS.intersection(relative.parts):
            continue
        target = dest / relative
        if source.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        data = source.read_bytes()
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:  # binary file: copied untouched
            target.write_bytes(data)
        else:
            target.write_text(_PLACEHOLDER.sub(project_name, text), encoding="utf-8", newline="")
        shutil.copymode(source, target)


class ForgejoGit:
    """Repositories, pull requests and tags on Forgejo.

    `merge` is refused (MergeRefused) unless CI is green, checked twice: here (through `ci`
    when given, otherwise through the commit statuses Forgejo holds) and by the branch
    protection configured on the default branch, which Forgejo enforces by itself.
    """

    def __init__(
        self,
        settings: PackSettings,
        *,
        ci: CIProvider | None = None,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.settings = settings
        self.ci = ci
        self._sleep = sleep
        self._token = settings.forgejo_token.get_secret_value()
        self._base_url = settings.forgejo_url.rstrip("/")
        self._api = Api(
            f"{self._base_url}/api/v1",
            self._token,
            service="git",
            auth_scheme="token",
            timeout=settings.http_timeout_s,
            transport=transport,
        )
        self._login: str | None = settings.forgejo_owner or None

    def close(self) -> None:
        self._api.close()

    # -- helpers -----------------------------------------------------------------------

    @property
    def owner(self) -> str:
        if self._login is None:
            self._login = str(self._api.request("GET", "/user")["login"])
        return self._login

    def _split(self, repo: RepoRef) -> tuple[str, str]:
        parts = [p for p in urlsplit(repo.clone_url).path.removesuffix(".git").split("/") if p]
        if len(parts) < 2:
            raise ProviderError(f"unexpected repository URL for {repo.name}")
        return parts[-2], parts[-1]

    def _repo_path(self, repo: RepoRef) -> str:
        owner, name = self._split(repo)
        return f"/repos/{owner}/{name}"

    def _scrub(self, text: str) -> str:
        secrets = [self._token]
        if self._login:
            secrets.append(self._basic_header())
        for secret in secrets:
            if secret:
                text = text.replace(secret, "***")
        return text

    def _basic_header(self) -> str:
        return base64.b64encode(f"{self.owner}:{self._token}".encode()).decode()

    def _git(self, args: list[str], cwd: Path, home: Path) -> str:
        """Run git without persisting credentials: the token travels in the environment of
        this process only (never on the command line, never written to .git/config)."""
        env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": str(home),
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "http.extraHeader",
            "GIT_CONFIG_VALUE_0": f"Authorization: Basic {self._basic_header()}",
            "GIT_AUTHOR_NAME": self.settings.git_author_name,
            "GIT_AUTHOR_EMAIL": self.settings.git_author_email,
            "GIT_COMMITTER_NAME": self.settings.git_author_name,
            "GIT_COMMITTER_EMAIL": self.settings.git_author_email,
        }
        for key in ("SSL_CERT_FILE", "GIT_SSL_CAINFO"):
            if key in os.environ:
                env[key] = os.environ[key]
        try:
            done = subprocess.run(  # noqa: S603 - fixed argv, no shell
                ["git", *args],  # noqa: S607
                cwd=cwd,
                env=env,
                check=True,
                capture_output=True,
                text=True,
                timeout=self.settings.git_timeout_s,
            )
            return done.stdout.strip()
        except subprocess.CalledProcessError as exc:
            raise ProviderError(
                f"git {args[0]} failed: {self._scrub(exc.stderr.strip())[:500]}"
            ) from None
        except (subprocess.TimeoutExpired, OSError) as exc:
            raise ProviderError(f"git {args[0]} failed: {type(exc).__name__}") from None

    def _push_tree(self, clone_url: str, tree: Path) -> None:
        branch = self.settings.default_branch
        with tempfile.TemporaryDirectory(prefix="cobble-home-") as home:
            for args in (
                ["init", "-q", "-b", branch],
                ["add", "-A"],
                ["commit", "-q", "-m", "chore: initial commit from template"],
                ["remote", "add", "origin", clone_url],
                ["push", "-q", "origin", branch],
            ):
                self._git(args, tree, Path(home))

    # -- GitProvider -------------------------------------------------------------------

    def create_repo_from_template(self, name: str, template_dir: Path) -> RepoRef:
        if not _REPO_NAME.match(name):
            raise ValueError(f"invalid repository name: {name!r}")
        if not template_dir.is_dir():
            raise ValueError(f"template directory not found: {template_dir}")
        owner = self.owner
        self._api.request(
            "POST",
            "/user/repos",
            json={
                "name": name,
                "private": True,
                "auto_init": False,
                "default_branch": self.settings.default_branch,
                "description": "Generated by Cobble",
            },
        )
        repo = RepoRef(name=name, clone_url=f"{self._base_url}/{owner}/{name}.git")
        with tempfile.TemporaryDirectory(prefix="cobble-tree-") as tmp:
            tree = Path(tmp)
            render_template(template_dir, tree, name)
            self._push_tree(repo.clone_url, tree)
        self._wait_for_branch(repo)
        # After the first push: from now on the default branch only moves through merged
        # pull requests whose required checks are green.
        self.protect_default_branch(repo)
        return repo

    def _wait_for_branch(self, repo: RepoRef, attempts: int = 30) -> None:
        """The server indexes a push asynchronously: wait until the default branch is visible."""
        path = f"{self._repo_path(repo)}/branches/{self.settings.default_branch}"
        for attempt in range(attempts):
            try:
                self._api.request("GET", path)
                return
            except ProviderNotFound:
                if attempt + 1 < attempts:
                    self._sleep(1.0)
        raise ProviderError(f"the default branch of {repo.name} did not appear after the push")

    def protect_default_branch(self, repo: RepoRef) -> None:
        path = self._repo_path(repo)
        payload: Mapping[str, Any] = {
            "branch_name": self.settings.default_branch,
            "rule_name": self.settings.default_branch,
            "enable_push": False,
            "enable_push_whitelist": False,
            "enable_merge_whitelist": False,
            "enable_status_check": True,
            "status_check_contexts": [self.settings.required_check],
            "required_approvals": 0,
            "block_on_rejected_reviews": False,
            "dismiss_stale_approvals": False,
            # Even the repository owner (the service account is an admin) cannot merge over
            # a red or pending check.
            "apply_to_admins": True,
        }
        try:
            self._api.request("POST", f"{path}/branch_protections", json=payload)
        except ProviderConflict:  # already protected: bring the rule up to date
            rule = self.settings.default_branch
            self._api.request("PATCH", f"{path}/branch_protections/{rule}", json=payload)

    def open_merge_request(
        self, repo: RepoRef, source_branch: str, target_branch: str, title: str
    ) -> MergeRequestRef:
        path = self._repo_path(repo)
        try:
            pull = self._api.request(
                "POST",
                f"{path}/pulls",
                json={"head": source_branch, "base": target_branch, "title": title},
            )
        except ProviderConflict:  # a pull request already exists for this branch pair
            pulls = self._api.request("GET", f"{path}/pulls", params={"state": "open", "limit": 50})
            pull = next(
                (
                    p
                    for p in pulls
                    if p["head"]["ref"] == source_branch and p["base"]["ref"] == target_branch
                ),
                None,
            )
            if pull is None:
                raise
        return self._to_ref(repo, pull)

    @staticmethod
    def _to_ref(repo: RepoRef, pull: Mapping[str, Any]) -> MergeRequestRef:
        return MergeRequestRef(
            repo=repo,
            number=int(pull["number"]),
            source_branch=str(pull["head"]["ref"]),
            target_branch=str(pull["base"]["ref"]),
            head_sha=str(pull["head"].get("sha") or "") or None,
        )

    def merge_request(self, request: MergeRequestRef) -> MergeRequestRef:
        """The pull request as it is now (its head sha moves when the branch is pushed)."""
        path = self._repo_path(request.repo)
        return self._to_ref(
            request.repo, self._api.request("GET", f"{path}/pulls/{request.number}")
        )

    def merge(self, request: MergeRequestRef) -> None:
        path = self._repo_path(request.repo)
        pull = self._api.request("GET", f"{path}/pulls/{request.number}")
        if pull.get("merged"):
            return
        if pull.get("state") != "open":
            raise MergeRefused("the merge request is closed")
        head_sha = str(pull["head"]["sha"])
        self._require_green(request.repo, head_sha)
        for attempt in range(MERGE_ATTEMPTS):
            try:
                self._api.request(
                    "POST",
                    f"{path}/pulls/{request.number}/merge",
                    json={
                        "Do": self.settings.merge_style,
                        "head_commit_id": head_sha,
                        "delete_branch_after_merge": True,
                    },
                )
                return
            except ProviderError as exc:
                if exc.status not in _MERGE_REFUSED_STATUSES:
                    raise
                # Right after another merge moved the base branch, Forgejo refuses for a moment
                # while it recomputes mergeability. If the pull request reads as mergeable
                # again, ask once more instead of failing the task.
                if attempt + 1 < MERGE_ATTEMPTS and self._is_mergeable(path, request.number):
                    self._sleep(MERGE_RETRY_DELAY_S)
                    continue
                raise MergeRefused(str(exc)) from None

    def _is_mergeable(self, path: str, number: int) -> bool:
        pull = self._api.request("GET", f"{path}/pulls/{number}")
        return bool(pull.get("mergeable")) and not pull.get("merged")

    def _require_green(self, repo: RepoRef, head_sha: str) -> None:
        if self.ci is not None:
            status = self.ci.status(repo, head_sha)
            if status.state is not CIState.SUCCESS:
                raise MergeRefused(f"CI is {status.state.value}: {status.detail}".rstrip(": "))
            return
        path = self._repo_path(repo)
        try:
            combined = self._api.request("GET", f"{path}/commits/{head_sha}/status")
        except ProviderNotFound:
            combined = {"statuses": []}
        matching = [
            s
            for s in combined.get("statuses") or []
            if fnmatch.fnmatchcase(str(s.get("context", "")), self.settings.required_check)
        ]
        if not matching:
            raise MergeRefused("CI has not reported on this commit yet")
        bad = [s for s in matching if s.get("status") != "success"]
        if bad:
            raise MergeRefused(f"CI is {bad[0].get('status')}: {bad[0].get('context')}")

    def tag(self, repo: RepoRef, name: str, ref: str) -> None:
        try:
            self._api.request(
                "POST", f"{self._repo_path(repo)}/tags", json={"tag_name": name, "target": ref}
            )
        except ProviderConflict as exc:
            raise ProviderTagExists(str(exc), status=exc.status) from None

    def restore_tag(self, repo: RepoRef, tag: str, message: str) -> MergeRequestRef | None:
        """A merge request whose result has exactly the tree of `tag` (ADR 0007).

        A commit with the tag's tree and the current head of the default branch as its parent
        is pushed to `restore/<tag>`; merging it (the normal path: CI, protection) makes the
        default branch look like the tag without rewriting history. None when it already does.
        """
        if not _TAG_NAME.match(tag):
            raise ValueError(f"invalid tag name: {tag!r}")
        branch = f"restore/{tag}"
        default = self.settings.default_branch
        with tempfile.TemporaryDirectory(prefix="cobble-restore-") as tmp:
            home = Path(tmp) / "home"
            home.mkdir()
            work = Path(tmp) / "work"
            work.mkdir()
            self._git(["clone", "-q", "--no-checkout", repo.clone_url, str(work)], work, home)
            self._git(["fetch", "-q", "--tags", "origin"], work, home)
            tag_tree = self._git(["rev-parse", f"refs/tags/{tag}^{{tree}}"], work, home)
            head = self._git(["rev-parse", f"origin/{default}"], work, home)
            if tag_tree == self._git(["rev-parse", f"{head}^{{tree}}"], work, home):
                return None
            commit = self._git(["commit-tree", tag_tree, "-p", head, "-m", message], work, home)
            self._git(
                ["push", "-q", "--force", "origin", f"{commit}:refs/heads/{branch}"], work, home
            )
        request = self.open_merge_request(repo, branch, default, message)
        return MergeRequestRef(
            request.repo, request.number, request.source_branch, request.target_branch, commit
        )

    def diff(
        self, repo: RepoRef, base: str, head: str, *, request_number: int | None = None
    ) -> tuple[str, bool]:
        """Unified diff of `head` against `base`, cut at DIFF_LIMIT.

        Order: the pull request given by number (still answers after a merge deleted the
        branch), the pull request of the (base, head) pair, then a plain comparison. A branch
        that does not exist yet has an empty diff.
        """
        path = self._repo_path(repo)
        candidates: list[str] = []
        if request_number is not None:
            candidates.append(f"{path}/pulls/{request_number}.diff")
        else:
            try:
                pull = self._api.request("GET", f"{path}/pulls/{base}/{head}")
                candidates.append(f"{path}/pulls/{int(pull['number'])}.diff")
            except (ProviderNotFound, KeyError, TypeError, ValueError):
                pass
        candidates.append(f"{path}/compare/{base}...{head}.diff")
        for candidate in candidates:
            try:
                text = self._api.request("GET", candidate)
            except ProviderNotFound:
                continue
            return cap_diff(text if isinstance(text, str) else "")
        return "", False

    # -- conveniences used by the orchestrator tests and tooling ---------------------------

    def commit_files(
        self,
        repo: RepoRef,
        branch: str,
        files: Mapping[str, str],
        message: str,
        *,
        base: str | None = None,
    ) -> str:
        """Commit `files` (path -> text) on `branch`, creating it from `base` if needed.
        Returns the new head sha. Goes through the contents API: no clone needed."""
        path = self._repo_path(repo)
        base = base or self.settings.default_branch
        try:
            self._api.request("GET", f"{path}/branches/{branch}")
            exists = True
        except ProviderNotFound:
            exists = False
        operations = []
        for file_path, text in files.items():
            sha: str | None = None
            try:
                current = self._api.request(
                    "GET",
                    f"{path}/contents/{file_path}",
                    params={"ref": branch if exists else base},
                )
                sha = str(current["sha"])
            except ProviderNotFound:
                pass
            operation: dict[str, Any] = {
                "operation": "update" if sha else "create",
                "path": file_path,
                "content": base64.b64encode(text.encode()).decode(),
            }
            if sha:
                operation["sha"] = sha
            operations.append(operation)
        body: dict[str, Any] = {
            "branch": branch if exists else base,
            "message": message,
            "files": operations,
        }
        if not exists:
            body["new_branch"] = branch
        result = self._api.request("POST", f"{path}/contents", json=body)
        return str(result["commit"]["sha"])
