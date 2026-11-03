"""Builds the cost router from settings (shared by the worker and the internal LLM endpoint)."""

from __future__ import annotations

from redis import Redis
from sqlalchemy.orm import Session, sessionmaker

from cobble.config import Settings

from .budget import BudgetService
from .costs import CostRouter
from .gateway import LiteLLMGateway
from .policy import ModelPolicy


def build_cost_router(
    settings: Settings, sessions: sessionmaker[Session], redis: Redis
) -> CostRouter:
    gateway = LiteLLMGateway(settings.litellm_url, settings.litellm_key, sessions, redis)
    return CostRouter(
        gateway,
        BudgetService(sessions, redis),
        settings.role_models,
        ModelPolicy(sessions, settings).default,
    )
