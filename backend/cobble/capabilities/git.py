"""Git capability: repositories, merge requests and tags. The core never names a product."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


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
