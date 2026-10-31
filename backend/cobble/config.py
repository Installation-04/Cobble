"""Runtime configuration, read from COBBLE_* environment variables."""

from __future__ import annotations

from decimal import Decimal
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="COBBLE_", extra="ignore")

    database_url: str = "postgresql+psycopg://cobble:cobble@localhost:5432/cobble"
    redis_url: str = "redis://localhost:6379/0"
    litellm_url: str = "http://localhost:4000"
    litellm_key: str = ""
    default_model: str = "fake"
    # Role -> model name known to LiteLLM, e.g. COBBLE_ROLE_MODELS='{"planner": "strong"}'.
    # Roles not listed use `default_model`.
    role_models: dict[str, str] = {}
    # Hard cap applied to every new project, in USD (0 or unset in a project = see API).
    default_budget_usd: Decimal = Decimal("5.00")
    # Cost estimate shown with a plan: tokens per task size (before the x1.5 test-writer and
    # reviewer passes) and the price per 1000 tokens in USD.
    estimate_tokens_s: int = 20_000
    estimate_tokens_m: int = 50_000
    estimate_usd_per_1k_tokens: Decimal = Decimal("0.002")
    lang: str = "en"
    public_url: str = "http://localhost:8080"
    cookie_secure: bool = False
    # Secret used to sign the per-run tokens that agents present to the internal LLM endpoint.
    run_token_secret: str = ""
    # Internal HTTP API of the agent-service (the only component that touches Docker).
    agent_service_url: str = "http://agent-service:8090"
    agent_service_token: str = ""
    # Base URL agents use to reach the internal LLM endpoint (seen from the agent network).
    internal_api_url: str = "http://api:8000"
    # --- scheduler (ADR 0006) ---
    max_parallel_agents: int = 2
    # Failed worker attempts before the task is escalated to `escalation_model`; the task fails
    # after `max_attempts` failed attempts. Empty `escalation_model`: the planner role's model.
    escalate_after: int = 2
    max_attempts: int = 4
    escalation_model: str = ""
    # Directory of the project template (mounted in the worker); the repository starts from it.
    template_dir: str = "/templates/fastapi-react"
    scheduler_interval_s: float = 5.0
    # Branch merge requests target.
    base_branch: str = "main"
    # A merge request whose CI stays pending this long counts as a failed attempt.
    ci_timeout_s: float = 1800.0
    # Per-run guardrails sent to the agent-service.
    agent_max_iterations: int = 20
    agent_max_seconds: int = 900
    agent_cpu: float = 1.0
    agent_memory_mb: int = 2048
    agent_pids: int = 256


@lru_cache
def get_settings() -> Settings:
    return Settings()
