"""Turns the modules that are really running into the providers the scheduler uses.

The module-manager says which modules run, what they provide and which secrets the core may
read (`core_secrets`). A registry maps a module id to the adapter that talks to it, so that
installing another module for a capability means registering one more adapter here and nothing
in the scheduler changes (ADR 0008). Only this package knows product names.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from pydantic import SecretStr

from cobble.capabilities.agent import AgentRunner
from cobble.capabilities.ci import CIProvider
from cobble.capabilities.git import GitProvider
from cobble.capabilities.preview import PreviewProvider

from .settings import PackSettings


@dataclass(frozen=True)
class Connection:
    module_id: str
    url: str
    provides: tuple[str, ...]
    secrets: Mapping[str, str] = field(repr=False)  # never printed

    @classmethod
    def from_json(cls, module_id: str, data: Mapping[str, Any]) -> Connection:
        return cls(
            module_id,
            str(data.get("url", "")),
            tuple(str(p) for p in data.get("provides", [])),
            {str(k): str(v) for k, v in dict(data.get("secrets", {})).items()},
        )


CIFactory = Callable[[Connection, PackSettings], CIProvider]
GitFactory = Callable[[Connection, PackSettings, CIProvider], GitProvider]
AgentFactory = Callable[[Connection], AgentRunner]
PreviewFactory = Callable[[Connection], PreviewProvider]


@dataclass(frozen=True)
class BuiltProviders:
    git: GitProvider
    ci: CIProvider
    git_module: str
    ci_module: str
    # Optional: without them the scheduler cannot start a task (agents) or show a demo (preview).
    agents: AgentRunner | None = None
    preview: PreviewProvider | None = None
    agents_module: str | None = None
    preview_module: str | None = None


class ProviderRegistry:
    def __init__(self) -> None:
        self._git: dict[str, GitFactory] = {}
        self._ci: dict[str, CIFactory] = {}
        self._agents: dict[str, AgentFactory] = {}
        self._preview: dict[str, PreviewFactory] = {}

    def register_git(self, module_id: str, factory: GitFactory) -> None:
        self._git[module_id] = factory

    def register_ci(self, module_id: str, factory: CIFactory) -> None:
        self._ci[module_id] = factory

    def register_agents(self, module_id: str, factory: AgentFactory) -> None:
        self._agents[module_id] = factory

    def register_preview(self, module_id: str, factory: PreviewFactory) -> None:
        self._preview[module_id] = factory

    def build(
        self, connections: Mapping[str, Connection], base: PackSettings
    ) -> BuiltProviders | None:
        """Providers for the first running module of each capability that has an adapter,
        or None when git or CI is missing (the scheduler then stays off)."""
        ci_conn = self._pick(connections, "ci", self._ci)
        git_conn = self._pick(connections, "git", self._git)
        if ci_conn is None or git_conn is None:
            return None
        ci = self._ci[ci_conn.module_id](ci_conn, base)
        git = self._git[git_conn.module_id](git_conn, base, ci)
        agents_conn = self._pick(connections, "agent-runner", self._agents)
        preview_conn = self._pick(connections, "preview", self._preview)
        return BuiltProviders(
            git,
            ci,
            git_conn.module_id,
            ci_conn.module_id,
            agents=self._agents[agents_conn.module_id](agents_conn) if agents_conn else None,
            preview=self._preview[preview_conn.module_id](preview_conn) if preview_conn else None,
            agents_module=agents_conn.module_id if agents_conn else None,
            preview_module=preview_conn.module_id if preview_conn else None,
        )

    @staticmethod
    def _pick(
        connections: Mapping[str, Connection], capability: str, adapters: Mapping[str, Any]
    ) -> Connection | None:
        for module_id in sorted(connections):
            conn = connections[module_id]
            if capability in conn.provides and module_id in adapters:
                return conn
        return None


def default_registry() -> ProviderRegistry:
    """The adapters shipped with Cobble."""
    registry = ProviderRegistry()

    def woodpecker(conn: Connection, base: PackSettings) -> CIProvider:
        from .woodpecker import WoodpeckerCI

        return WoodpeckerCI(
            base.model_copy(
                update={
                    "woodpecker_url": conn.url.rstrip("/") + "/ci",
                    "woodpecker_token": SecretStr(conn.secrets.get("api_token", "")),
                }
            )
        )

    def forgejo(conn: Connection, base: PackSettings, ci: CIProvider) -> GitProvider:
        from .forgejo import ForgejoGit

        return ForgejoGit(
            base.model_copy(
                update={
                    "forgejo_url": conn.url,
                    "forgejo_token": SecretStr(conn.secrets.get("api_token", "")),
                }
            ),
            ci=ci,
        )

    def aider(conn: Connection) -> AgentRunner:
        from .agent_service import HttpAgentRunner

        return HttpAgentRunner(conn.url, conn.secrets.get("service_token", ""))

    def preview(conn: Connection) -> PreviewProvider:
        from .preview_service import HttpPreviewProvider

        return HttpPreviewProvider(conn.url, conn.secrets.get("service_token", ""))

    registry.register_agents("aider", aider)
    registry.register_preview("preview", preview)
    registry.register_ci("woodpecker", woodpecker)
    registry.register_git("forgejo", forgejo)
    return registry
