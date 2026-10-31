"""In-memory PreviewProvider for tests and the fake pack mode."""

from __future__ import annotations

import uuid

from .preview import PreviewRequest, PreviewState, PreviewStatus, PreviewUnavailable


def preview_path(project_id: uuid.UUID, milestone: str) -> str:
    return f"/demo/{project_id}/{milestone}/"


class FakePreviewProvider:
    """`deploy` records the request; the preview is `building` for `polls_before_running`
    status calls, then `running` (or `failed` when `fail` is set)."""

    def __init__(self, *, polls_before_running: int = 0, fail: bool = False) -> None:
        self.polls_before_running = polls_before_running
        self.fail = fail
        self.unavailable = False
        self.deployed: list[PreviewRequest] = []
        self.removed: list[tuple[uuid.UUID, str]] = []
        self._current: dict[tuple[uuid.UUID, str], PreviewRequest] = {}
        self._polls: dict[tuple[uuid.UUID, str], int] = {}

    def deploy(self, request: PreviewRequest) -> PreviewStatus:
        if self.unavailable:
            raise PreviewUnavailable("fake preview service is down")
        key = (request.project_id, request.milestone)
        if self._current.get(key) != request:
            self.deployed.append(request)
            self._current[key] = request
            self._polls[key] = 0
        return PreviewStatus(PreviewState.BUILDING, preview_path(*key))

    def status(self, project_id: uuid.UUID, milestone: str) -> PreviewStatus | None:
        if self.unavailable:
            raise PreviewUnavailable("fake preview service is down")
        key = (project_id, milestone)
        if key not in self._current:
            return None
        self._polls[key] += 1
        path = preview_path(*key)
        if self.fail:
            return PreviewStatus(PreviewState.FAILED, path, "build failed")
        if self._polls[key] <= self.polls_before_running:
            return PreviewStatus(PreviewState.BUILDING, path)
        return PreviewStatus(PreviewState.RUNNING, path)

    def remove(self, project_id: uuid.UUID, milestone: str) -> None:
        self.removed.append((project_id, milestone))
        self._current.pop((project_id, milestone), None)
