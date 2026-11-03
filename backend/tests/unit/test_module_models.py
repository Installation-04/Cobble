"""Defaults of the module tables (the constraints themselves are tested on Postgres)."""

from __future__ import annotations

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from cobble.db.base import Base
from cobble.db.models import Module, ModuleEvent, ModuleLink, ModuleSecret, PlatformState


def _session() -> Session:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_a_new_module_is_installing_and_not_explicit() -> None:
    with _session() as session:
        session.add(Module(id="forgejo", version="15.0.11"))
        session.commit()
        module = session.get(Module, "forgejo")
        assert module is not None
        assert (module.state, module.explicit, module.settings) == ("installing", False, {})
        assert module.variant is None
        assert module.last_error is None
        assert module.installed_at is not None


def test_secrets_links_and_events_have_safe_defaults() -> None:
    with _session() as session:
        session.add_all([Module(id="forgejo", version="1"), Module(id="woodpecker", version="1")])
        session.add(ModuleSecret(module_id="forgejo", key="api_token", ciphertext=b"x", nonce=b"n"))
        session.add(ModuleLink(consumer="woodpecker", provider="forgejo", capability="git"))
        session.add(ModuleEvent(module_id="forgejo", kind="install"))
        session.commit()
        secret = session.scalars(select(ModuleSecret)).one()
        assert secret.key_version == 1
        assert session.scalars(select(ModuleLink)).one().state == "pending"
        event = session.scalars(select(ModuleEvent)).one()
        assert (event.outcome, event.params) == ("ok", {})


def test_the_platform_state_starts_unconfigured() -> None:
    with _session() as session:
        session.add(PlatformState())
        session.commit()
        state = session.get(PlatformState, 1)
        assert state is not None
        assert (state.setup_completed, state.modules_generation) == (False, 0)
