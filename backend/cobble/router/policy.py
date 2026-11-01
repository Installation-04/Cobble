"""Which model answers: the one chosen in the product, else the configured one.

The administrator connects a model service and makes it the default from the product (the
platform state); until then the configured `default_model` applies (`fake` in development). The
choice is read at every call, so changing it takes effect at once with no restart. A role can
still be pinned to a model with `COBBLE_ROLE_MODELS` (the full per-role routing is v0.3).
"""

from __future__ import annotations

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from cobble.capabilities.llm import Role
from cobble.config import Settings
from cobble.db.models import PlatformState


class ModelPolicy:
    def __init__(self, sessions: sessionmaker[Session], settings: Settings) -> None:
        self._sessions = sessions
        self._settings = settings

    def default(self) -> str:
        try:
            with self._sessions() as session:
                state = session.get(PlatformState, 1)
                chosen = state.default_model if state is not None else None
        except SQLAlchemyError:
            chosen = None  # a database hiccup must not make every call fail on its own
        return chosen or self._settings.default_model

    def model_for(self, role: Role) -> str:
        return self._settings.role_models.get(role.value) or self.default()
