"""Builds the scheduler from the settings, or says why it cannot (never raises).

The fixed pack's providers are imported lazily and defensively: a worker started without a
configured pack still plans (interview, spec, plan) and only the build loop is disabled.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from redis import Redis
from sqlalchemy.orm import Session, sessionmaker

from cobble.config import Settings
from cobble.db.models import PlatformState
from cobble.router.policy import ModelPolicy

from .engine import Scheduler
from .supervisor import BuildResult, SchedulerSupervisor

log = logging.getLogger(__name__)

PACK_ENV_FILE = "COBBLE_PACK_ENV_FILE"


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
    from cobble.providers.module_manager import HttpModuleManager, ModuleManagerUnavailable
    from cobble.providers.registry import Connection, default_registry

    client = HttpModuleManager.from_settings(settings)
    registry = default_registry()
    supervisor: SchedulerSupervisor | None = None
    unreachable = False  # log the outage once, not at every retry

    def build() -> BuildResult:
        nonlocal unreachable
        try:
            raw = client.connections()
        except ModuleManagerUnavailable:
            if not unreachable:
                log.warning("module-manager unreachable, using what is already running")
                unreachable = True
            if supervisor is not None and supervisor.current is not None:
                return BuildResult(None, final=False, keep=True)
            return BuildResult(build_scheduler(settings, sessions, redis), final=False)
        unreachable = False
        connections = {mid: Connection.from_json(mid, data) for mid, data in raw.items()}
        from cobble.providers.agent_service import build_runtime_services
        from cobble.providers.settings import load_settings

        env_file = os.environ.get(PACK_ENV_FILE)
        built = registry.build(connections, load_settings(Path(env_file) if env_file else None))
        if built is None:
            # No git+ci module installed: the v0.1 pack (configured by files) still works.
            return BuildResult(build_scheduler(settings, sessions, redis))
        runtime = build_runtime_services(settings)
        if runtime is None:
            return BuildResult(None)
        agents, preview = runtime

        model_for = ModelPolicy(sessions, settings).model_for

        return BuildResult(
            Scheduler(
                sessions,
                built.git,
                built.ci,
                agents,
                settings,
                redis=redis,
                model_for=model_for,
                preview=preview,
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
    """A scheduler wired to the pack, or None (and a log line) when it is not available."""
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
    if not settings.run_token_secret:
        log.warning("scheduler disabled: COBBLE_RUN_TOKEN_SECRET is not set")
        return None
    try:
        from cobble.providers.agent_service import build_pack_services

        env_file = os.environ.get(PACK_ENV_FILE)
        services = build_pack_services(settings, Path(env_file) if env_file else None)
    except ImportError:
        log.warning("scheduler disabled: the pack providers are not importable", exc_info=True)
        return None
    except Exception:
        log.warning("scheduler disabled: the pack could not be configured", exc_info=True)
        return None
    if services is None:
        log.warning("scheduler disabled: the pack is not configured")
        return None

    model_for = ModelPolicy(sessions, settings).model_for

    return Scheduler(
        sessions,
        services.git,
        services.ci,
        services.agents,
        settings,
        redis=redis,
        model_for=model_for,
        preview=services.preview,
    )
