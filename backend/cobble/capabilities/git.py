"""Git capability: repositories, merge requests and tags. The core never names a product."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

# A diff longer than this many characters is cut (at a line boundary) and flagged truncated.
DIFF_LIMIT = 200_000


def cap_diff(text: str, limit: int = DIFF_LIMIT) -> tuple[str, bool]:
    """`text` cut to at most `limit` characters, on a line boundary when possible."""
    if len(text) <= limit:
        return text, False
    cut = text[:limit]
    newline = cut.rfind("\n")
    return (cut[: newline + 1] if newline > 0 else cut), True


class TagExists(Exception):
    """The tag already exists (a retried tagging step): the scheduler treats it as done."""


class MergeRefused(Exception):
    """The merge was refused (for example CI is not green)."""


@dataclass(frozen=True)
class RepoRef:
    name: str
    clone_url: str


@dataclass(frozen=True)
class MergeRequestRef:
    repo: RepoRef
    number: int
    source_branch: str
    target_branch: str
    head_sha: str | None = None


class GitProvider(Protocol):
    def create_repo_from_template(self, name: str, template_dir: Path) -> RepoRef:
        """Create a repository whose first commit is the content of `template_dir`."""
        ...

    def open_merge_request(
        self, repo: RepoRef, source_branch: str, target_branch: str, title: str
    ) -> MergeRequestRef: ...

    def merge(self, request: MergeRequestRef) -> None:
        """Merge. Raises MergeRefused when the provider's rules (CI) do not allow it."""
        ...

    def tag(self, repo: RepoRef, name: str, ref: str) -> None: ...

    def diff(
        self, repo: RepoRef, base: str, head: str, *, request_number: int | None = None
    ) -> tuple[str, bool]:
        """Unified diff of `head` against `base` and whether it was truncated (DIFF_LIMIT).

        `request_number` (a known merge request) lets the provider answer even after the head
        branch was deleted by the merge. Empty when there is nothing to compare yet.
        """
        ...

    def restore_tag(self, repo: RepoRef, tag: str, message: str) -> MergeRequestRef | None:
        """Open a merge request whose content is the tree of `tag` (ADR 0007).

        The request is merged through the normal path (`merge`), so CI and branch protection
        still apply. Idempotent. Returns None when the default branch already has that tree.
        """
        ...
