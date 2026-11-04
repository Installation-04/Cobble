"""Which models are served on this machine, and which projects may use nothing else.

Confidential projects (`local_only`) must never send a request to a model service outside this
machine. The cost router asks this module for the names of the local models; when it cannot
find out (the module-manager is down, no token) the answer is "none": the safe direction.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Callable
from typing import Any

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from cobble.db import Project

log = logging.getLogger(__name__)


class LocalModels:
    """The names of the models served here, read from the module-manager and kept a few seconds."""

    def __init__(
        self,
        fetch: Callable[[], dict[str, Any]],
        *,
        ttl_s: float = 10.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._fetch = fetch
        self._ttl_s = ttl_s
        self._clock = clock
        self._names: set[str] = set()
        self._at: float | None = None

    def __call__(self) -> set[str]:
        now = self._clock()
        if self._at is not None and now - self._at < self._ttl_s:
            return set(self._names)
        try:
            listing = self._fetch()
            self._names = {str(m["name"]) for m in listing.get("local", []) if "name" in m}
        except Exception:  # unreachable, refused, malformed: no local model is known
            log.warning(
                "cannot list the local models: local-only projects will refuse", exc_info=True
            )
            self._names = set()
        self._at = now
        return set(self._names)


def project_is_local_only(sessions: sessionmaker[Session]) -> Callable[[uuid.UUID], bool]:
    """A project that cannot be read counts as local-only: when unsure, nothing leaves."""

    def check(project_id: uuid.UUID) -> bool:
        try:
            with sessions() as session:
                project = session.get(Project, project_id)
                return bool(project.local_only) if project is not None else False
        except SQLAlchemyError:
            return True

    return check
