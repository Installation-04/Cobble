"""Builds the cost router from settings (shared by the worker and the internal LLM endpoint)."""

from __future__ import annotations

from redis import Redis
from sqlalchemy.orm import Session, sessionmaker

from cobble.config import Settings

from .budget import BudgetService
from .costs import CostRouter
from .gateway import LiteLLMGateway
from .local import LocalModels, project_is_local_only
from .policy import ModelPolicy


def _local_models(settings: Settings) -> LocalModels:
    def fetch() -> dict[str, object]:
        from cobble.providers.module_manager import HttpModuleManager

        if not settings.module_manager_token:
            return {}
        client = HttpModuleManager.from_settings(settings)
        try:
            return client.models()
        finally:
            client.close()

    return LocalModels(fetch)


def build_cost_router(
    settings: Settings, sessions: sessionmaker[Session], redis: Redis
) -> CostRouter:
    gateway = LiteLLMGateway(settings.litellm_url, settings.litellm_key, sessions, redis)
    policy = ModelPolicy(sessions, settings)
    return CostRouter(
        gateway,
        BudgetService(sessions, redis),
        settings.role_models,
        policy.default,
        chain_for=policy.chain_for,
        is_local_only=project_is_local_only(sessions),
        local_models=_local_models(settings),
    )
