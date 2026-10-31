"""CI capability: run checks on a branch and report the result."""

from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import Protocol

from .git import RepoRef


class CIState(enum.StrEnum):
    PENDING = "pending"
    SUCCESS = "success"
    FAILURE = "failure"


@dataclass(frozen=True)
class CIStatus:
    state: CIState
    detail: str = ""


class CIProvider(Protocol):
    def activate(self, repo: RepoRef) -> None:
        """Enable CI for the repository (webhook, secrets...)."""
        ...

    def status(self, repo: RepoRef, ref: str) -> CIStatus: ...

    def wait(self, repo: RepoRef, ref: str, timeout_s: float) -> CIStatus:
        """Block until the CI of `ref` is no longer pending, or the timeout expires."""
        ...
