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

from cobble.capabilities.llm import Role
from cobble.config import Settings

from .engine import Scheduler

log = logging.getLogger(__name__)

PACK_ENV_FILE = "COBBLE_PACK_ENV_FILE"


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

    def model_for(role: Role) -> str:
        return settings.role_models.get(role.value, settings.default_model)

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
