"""Which model answers a role: the routes set in the product, else the configured ones.

The administrator connects model services and, per role, orders the models to try (the first
one, then each fallback if it cannot answer): `ModelPolicy.chain_for`. Until a route is set, the
role follows the configured `role_models` (`COBBLE_ROLE_MODELS`), and then the platform default
(the model made the default in the product, else the configured `default_model`, `fake` in
development). Everything is read at each call, so a change applies at once with no restart.

The `escalation` role is the model a task moves to after repeated failures; unset, it is
`COBBLE_ESCALATION_MODEL`, and then the `planner` role's chain.
"""

from __future__ import annotations

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from cobble.capabilities.llm import Role
from cobble.config import Settings
from cobble.db.models import PlatformState

ROLES: tuple[Role, ...] = (
    Role.PLANNER,
    Role.TEST_WRITER,
    Role.WORKER,
    Role.REVIEWER,
    Role.ESCALATION,
)
MAX_CHAIN = 4  # a longer chain only delays the failure the user needs to see


class ModelPolicy:
    def __init__(self, sessions: sessionmaker[Session], settings: Settings) -> None:
        self._sessions = sessions
        self._settings = settings

    def _state(self) -> tuple[str | None, dict[str, list[str]]]:
        try:
            with self._sessions() as session:
                state = session.get(PlatformState, 1)
                if state is None:
                    return None, {}
                return state.default_model, dict(state.role_routes or {})
        except SQLAlchemyError:
            return None, {}  # a database hiccup must not make every call fail on its own

    def default(self) -> str:
        return self._state()[0] or self._settings.default_model

    def routes(self) -> dict[str, list[str]]:
        """The routes set in the product, by role (only roles that have one)."""
        return {role: list(chain) for role, chain in self._state()[1].items() if chain}

    def chain_for(self, role: Role) -> list[str]:
        """Models to try for `role`, best first; never empty."""
        chosen, routes = self._state()
        default = chosen or self._settings.default_model
        route = routes.get(role.value)
        if route:
            return list(dict.fromkeys(route))[:MAX_CHAIN]
        pinned = self._settings.role_models.get(role.value)
        if pinned:
            return [pinned]
        if role is Role.ESCALATION:
            if self._settings.escalation_model:
                return [self._settings.escalation_model]
            return self.chain_for(Role.PLANNER)
        return [default]

    def model_for(self, role: Role) -> str:
        return self.chain_for(role)[0]
