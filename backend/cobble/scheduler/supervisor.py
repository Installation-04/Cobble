"""Keeps the scheduler in step with the installed modules.

The scheduler is built from the providers of the modules that run. When the module-manager
changes them (`platform_state.modules_generation` moves) the supervisor builds a new scheduler
and swaps it in *between two ticks*, so a tick never sees providers change under it. If the
manager cannot be reached the current scheduler keeps running and the build is retried.
"""

from __future__ import annotations

import logging
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass

from .engine import Scheduler

log = logging.getLogger(__name__)


class SchedulerUnavailable(Exception):
    """No scheduler is configured right now (no git/CI module, no agent service)."""


@dataclass(frozen=True)
class BuildResult:
    scheduler: Scheduler | None
    # False: the answer may change without the generation moving (manager unreachable): retry.
    final: bool = True
    # True: nothing could be learned, leave the running scheduler as it is.
    keep: bool = False


class SchedulerSupervisor:
    def __init__(
        self,
        build: Callable[[], BuildResult],
        generation: Callable[[], int],
        interval_s: float,
    ) -> None:
        self._build = build
        self._generation = generation
        self._interval_s = interval_s
        self._lock = threading.Lock()
        self._current: Scheduler | None = None
        self._seen: int | None = None  # generation the current scheduler was built for
        self._settled = False

    @property
    def current(self) -> Scheduler | None:
        with self._lock:
            return self._current

    def refresh(self) -> bool:
        """Rebuild when the modules changed. True when the scheduler was replaced."""
        try:
            generation = self._generation()
        except Exception:
            log.warning("cannot read the modules generation, keeping the scheduler", exc_info=True)
            return False
        if self._settled and generation == self._seen:
            return False
        try:
            result = self._build()
        except Exception:
            log.exception("building the scheduler failed, keeping the current one")
            return False
        if result.keep:
            return False
        with self._lock:
            self._current = result.scheduler
        self._seen = generation
        self._settled = result.final
        if result.scheduler is not None:
            try:
                result.scheduler.reconcile()
            except Exception:
                log.exception("scheduler reconcile failed")
        log.info(
            "scheduler %s (modules generation %s)",
            "ready" if result.scheduler is not None else "off",
            generation,
        )
        return True

    def run_forever(self, stop: threading.Event) -> None:
        while not stop.is_set():
            self.refresh()
            scheduler = self.current
            if scheduler is not None:
                try:
                    scheduler.tick()
                except Exception:
                    log.exception("scheduler tick failed")
            stop.wait(self._interval_s)

    def _require(self) -> Scheduler:
        scheduler = self.current
        if scheduler is None:
            raise SchedulerUnavailable
        return scheduler

    def run_start_job(self, project_id: uuid.UUID) -> bool:
        return self._require().run_start_job(project_id)

    def run_revert_job(self, project_id: uuid.UUID, ref: str) -> bool:
        return self._require().run_revert_job(project_id, ref)
