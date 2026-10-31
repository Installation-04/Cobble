"""Preview capability: deploy a tagged state of a project as a browsable demo (ADR 0007)."""

from __future__ import annotations

import enum
import uuid
from dataclasses import dataclass
from typing import Protocol


class PreviewState(enum.StrEnum):
    BUILDING = "building"
    RUNNING = "running"
    FAILED = "failed"


class PreviewUnavailable(Exception):
    """The preview service could not be reached or failed: retry later."""


class PreviewRejected(Exception):
    """The preview service refused the request (bad input or credentials)."""


@dataclass(frozen=True)
class PreviewRequest:
    project_id: uuid.UUID
    milestone: str  # M1
    repo_clone_url: str
    ref: str  # the tag to build


@dataclass(frozen=True)
class PreviewStatus:
    state: PreviewState
    path: str  # URL path of the demo, e.g. /demo/<project_id>/M1/
    detail: str = ""


class PreviewProvider(Protocol):
    def deploy(self, request: PreviewRequest) -> PreviewStatus:
        """Build and run `request.ref`; idempotent for the same (project, milestone, ref).
        Returns at once (state `building`); raises PreviewUnavailable / PreviewRejected."""
        ...

    def status(self, project_id: uuid.UUID, milestone: str) -> PreviewStatus | None:
        """None when the service does not know this preview."""
        ...

    def remove(self, project_id: uuid.UUID, milestone: str) -> None: ...
