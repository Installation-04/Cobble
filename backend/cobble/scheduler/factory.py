"""Builds the scheduler from the settings, or says why it cannot (never raises).

With the fake pack the scheduler runs on in-memory fakes (browser tests, development). Otherwise
it is built from the modules that are really running: the module-manager says which ones, and
the provider registry maps them to adapters (ADR 0008). Without a Git, a CI and an agent module
there is no scheduler yet: planning (interview, spec, plan) still works, building waits.
"""

from __future__ import annotations

import logging

from redis import Redis
from sqlalchemy.orm import Session, sessionmaker

from cobble.config import Settings
from cobble.db.models import PlatformState
from cobble.router.policy import ModelPolicy

from .engine import Scheduler
from .supervisor import BuildResult, SchedulerSupervisor

log = logging.getLogger(__name__)


def make_scheduler_supervisor(
    settings: Settings, sessions: sessionmaker[Session], redis: Redis | None
) -> SchedulerSupervisor | None:
    """A supervisor that follows the installed modules, or None when modules are not in use
    (fake pack, or no module-manager token): the caller then uses `build_scheduler`."""
    if settings.pack_mode == "fake" or not settings.module_manager_token:
        return None
    if not settings.run_token_secret:
        log.warning("scheduler disabled: COBBLE_RUN_TOKEN_SECRET is not set")
        return None
    from cobble.providers.module_manager import ModuleManagerUnavailable
    from cobble.providers.runtime import build_from_modules

    supervisor: SchedulerSupervisor | None = None
    unreachable = False  # log the outage once, not at every retry
    missing: set[str] = set()  # log what is missing once per change, not at every retry

    def build() -> BuildResult:
        nonlocal unreachable
        try:
            built = build_from_modules(settings)
        except ModuleManagerUnavailable:
            if not unreachable:
                log.warning("module-manager unreachable, using what is already running")
                unreachable = True
            if supervisor is not None and supervisor.current is not None:
                return BuildResult(None, final=False, keep=True)
            return BuildResult(None, final=False)
        unreachable = False
        needed = {
            "git and ci modules": built is not None,
            "an agent-runner module": built is not None and built.agents is not None,
        }
        lacking = {name for name, present in needed.items() if not present}
        if lacking != missing:
            missing.clear()
            missing.update(lacking)
            if lacking:
                log.warning("scheduler waiting for: %s", ", ".join(sorted(lacking)))
        if built is None or built.agents is None:
            return BuildResult(None)
        return BuildResult(
            Scheduler(
                sessions,
                built.git,
                built.ci,
                built.agents,
                settings,
                redis=redis,
                model_for=ModelPolicy(sessions, settings).model_for,
                preview=built.preview,
            )
        )

    def generation() -> int:
        with sessions() as session:
            state = session.get(PlatformState, 1)
            return state.modules_generation if state is not None else 0

    supervisor = SchedulerSupervisor(build, generation, settings.scheduler_interval_s)
    return supervisor


def build_scheduler(
    settings: Settings, sessions: sessionmaker[Session], redis: Redis | None
) -> Scheduler | None:
    """The scheduler on fakes (fake pack mode), or None with a log line."""
    if settings.pack_mode == "fake":
        from .fakepack import FAKE_RUN_TOKEN_SECRET, build_fake_services

        if not settings.run_token_secret:
            settings = settings.model_copy(update={"run_token_secret": FAKE_RUN_TOKEN_SECRET})
        fake = build_fake_services(settings)
        return Scheduler(
            sessions,
            fake.git,
            fake.ci,
            fake.agents,
            settings,
            redis=redis,
            preview=fake.preview,
        )
    log.warning("scheduler disabled: no module-manager token (install the modules to build)")
    return None
