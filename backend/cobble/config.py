"""Runtime configuration, read from COBBLE_* environment variables."""

from __future__ import annotations

from decimal import Decimal
from functools import lru_cache
from typing import Literal

from pydantic import field_validator, model_validator
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
    # Internal HTTP API of the module-manager (the only component with the vault key and Docker).
    module_manager_url: str = "http://module-manager:8095"
    module_manager_token: str = ""
    # Module-manager only: where its master key lives (created at first start), the catalogue
    # directory (mounted at the same absolute path as on the host, see core/compose.yml) and the
    # machine's facts (0 / "auto": detect; the installer writes what it found).
    module_master_key_file: str = "/var/lib/cobble-keys/master.key"
    module_catalog_dir: str = "/opt/cobble/catalog"
    module_ram_mb: int = 0
    module_gpu: Literal["auto", "none", "nvidia", "amd"] = "auto"
    module_health_timeout_s: float = 120.0
    # The reverse proxy: where the module routes are written, the main Caddyfile to reload with
    # them, and Caddy's admin socket. An empty routes dir means "no proxy to configure".
    # How users reach the platform, e.g. http://192.168.1.20 : modules build their public links
    # from it (COBBLE_PUBLIC_URL / COBBLE_PUBLIC_HOST in their compose files and hooks).
    module_public_url: str = "http://localhost"
    # Extra variables every module compose file and hook may use (for example a CA bundle for
    # pipeline steps behind a TLS-inspecting proxy). Operator-chosen, never secrets.
    # JSON object, e.g. {"COBBLE_SKIP_STEPS": "trivy"}. Empty: none.
    module_extra_env: str = ""
    module_routes_dir: str = ""
    module_caddyfile: str = "/etc/caddy-main/Caddyfile"
    module_caddy_admin_socket: str = "/run/caddy/admin.sock"
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
    # --- demo (ADR 0007) ---
    # Internal HTTP API of the preview-service (the component that builds and runs the demos).
    preview_service_url: str = "http://preview-service:8091"
    preview_service_token: str = ""
    # `real`: the fixed pack (git server, CI, agent-service, preview-service). `fake`:
    # in-memory fakes that play the whole loop in seconds, for development and browser tests.
    # Refused when `env` is `production`.
    pack_mode: Literal["real", "fake"] = "real"
    env: str = "development"
    # Fake pack only: seconds between two steps of a simulated agent run.
    fake_step_s: float = 0.3

    @field_validator("pack_mode", mode="before")
    @classmethod
    def _empty_pack_mode_means_real(cls, value: object) -> object:
        # The compose file forwards COBBLE_PACK_MODE even when it is not set: an empty string.
        return "real" if value is None or str(value).strip() == "" else value

    @model_validator(mode="after")
    def _fake_pack_rules(self) -> Settings:
        if self.pack_mode == "fake":
            if self.env.lower() == "production":
                raise ValueError("COBBLE_PACK_MODE=fake is refused when COBBLE_ENV=production")
            if "scheduler_interval_s" not in self.model_fields_set:
                self.scheduler_interval_s = 0.5  # the fake loop should feel quick
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
