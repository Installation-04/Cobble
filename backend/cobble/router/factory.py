"""Builds the cost router from settings (shared by the worker and the internal LLM endpoint)."""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal

import httpx
from redis import Redis
from sqlalchemy.orm import Session, sessionmaker

from cobble.capabilities.llm import Role
from cobble.config import Settings

from .budget import BudgetService
from .cost_settings import ElectricityMeter
from .costs import SHARED_BACKOFF, CostRouter
from .gateway import LiteLLMGateway
from .local import LocalModels, project_is_local_only
from .policy import ModelPolicy
from .prices import PriceBook


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
    local_models = _local_models(settings)
    gateway = LiteLLMGateway(
        settings.litellm_url,
        settings.litellm_key,
        sessions,
        redis,
        electricity=ElectricityMeter(sessions, local_models),
    )
    policy = ModelPolicy(sessions, settings)
    return CostRouter(
        gateway,
        BudgetService(sessions, redis, settings),
        settings.role_models,
        policy.default,
        chain_for=policy.chain_for,
        is_local_only=project_is_local_only(sessions),
        local_models=local_models,
        backoff=SHARED_BACKOFF,
    )


def build_role_price(
    settings: Settings, sessions: sessionmaker[Session]
) -> Callable[[Role], Decimal | None]:
    """USD per 1000 tokens of the model a role tries first, for the plan estimate (ADR 0021).

    A model served here or a free tier costs 0; a model the gateway cannot price has no price
    (the estimate then uses its flat configured price for that role)."""
    from cobble.orchestrator.estimate import blended_per_1k

    from . import price_table

    policy = ModelPolicy(sessions, settings)
    local = _local_models(settings)
    headers = {"Authorization": f"Bearer {settings.litellm_key}"} if settings.litellm_key else {}
    book = PriceBook(httpx.Client(base_url=settings.litellm_url.rstrip("/"), headers=headers))

    def role_price(role: Role) -> Decimal | None:
        model = policy.chain_for(role)[0]
        if model in local():
            return Decimal(0)
        with sessions() as session:
            free = price_table.free_names(session)
        if model in free or price_table.has_free_name(model):
            return Decimal(0)
        prices = book.prices(model)
        if prices is None:
            return None
        return blended_per_1k(prices.prompt, prices.completion)

    return role_price
