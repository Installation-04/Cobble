from __future__ import annotations

import logging
import sys

import pytest
from sqlalchemy.orm import Session, sessionmaker

from cobble.config import Settings
from cobble.scheduler.factory import build_scheduler


def test_no_run_token_secret_disables_the_scheduler(
    sessions: sessionmaker[Session], caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING):
        assert build_scheduler(Settings(run_token_secret=""), sessions, None) is None
    assert "COBBLE_RUN_TOKEN_SECRET" in caplog.text


def test_unconfigured_pack_disables_the_scheduler(
    sessions: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("COBBLE_PACK_FORGEJO_TOKEN", raising=False)
    monkeypatch.delenv("COBBLE_PACK_WOODPECKER_TOKEN", raising=False)
    assert build_scheduler(Settings(run_token_secret="s"), sessions, None) is None


def test_missing_providers_do_not_crash(
    sessions: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(sys.modules, "cobble.providers.agent_service", None)  # import fails
    assert build_scheduler(Settings(run_token_secret="s"), sessions, None) is None


def test_configured_pack_builds_a_scheduler(
    sessions: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("COBBLE_PACK_FORGEJO_TOKEN", "a")
    monkeypatch.setenv("COBBLE_PACK_WOODPECKER_TOKEN", "b")
    scheduler = build_scheduler(
        Settings(run_token_secret="s", agent_service_token="t"), sessions, None
    )
    assert scheduler is not None


# --- following the installed modules ----------------------------------------------------------

from typing import Any  # noqa: E402

from cobble.db.models import PlatformState  # noqa: E402
from cobble.providers.module_manager import (  # noqa: E402
    HttpModuleManager,
    ModuleManagerUnavailable,
)
from cobble.scheduler.factory import make_scheduler_supervisor  # noqa: E402

CONNECTIONS = {
    "forgejo": {"url": "http://forgejo:3000", "provides": ["git"], "secrets": {"api_token": "g"}},
    "woodpecker": {
        "url": "http://woodpecker-server:8000",
        "provides": ["ci"],
        "secrets": {"api_token": "c"},
    },
}


def configured(**extra: Any) -> Settings:
    return Settings(
        run_token_secret="s", agent_service_token="t", module_manager_token="m", **extra
    )


def test_modules_are_not_followed_without_a_manager_token_or_in_fake_mode(
    sessions: sessionmaker[Session],
) -> None:
    assert make_scheduler_supervisor(Settings(run_token_secret="s"), sessions, None) is None
    fake = Settings(run_token_secret="s", module_manager_token="m", pack_mode="fake")
    assert make_scheduler_supervisor(fake, sessions, None) is None
    assert make_scheduler_supervisor(Settings(module_manager_token="m"), sessions, None) is None


def test_running_git_and_ci_modules_give_a_scheduler(
    sessions: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(HttpModuleManager, "connections", lambda self: CONNECTIONS)
    supervisor = make_scheduler_supervisor(configured(), sessions, None)
    assert supervisor is not None
    assert supervisor.refresh() is True
    scheduler = supervisor.current
    assert scheduler is not None
    assert scheduler._git.settings.forgejo_token.get_secret_value() == "g"  # type: ignore[attr-defined]
    assert scheduler._ci.settings.woodpecker_token.get_secret_value() == "c"  # type: ignore[attr-defined]


def test_a_new_modules_generation_rebuilds_with_the_new_connections(
    sessions: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    current: dict[str, Any] = dict(CONNECTIONS)
    monkeypatch.setattr(HttpModuleManager, "connections", lambda self: current)
    supervisor = make_scheduler_supervisor(configured(), sessions, None)
    assert supervisor is not None
    supervisor.refresh()
    first = supervisor.current
    assert supervisor.refresh() is False  # nothing moved
    current["forgejo"] = {**CONNECTIONS["forgejo"], "secrets": {"api_token": "rotated"}}
    with sessions() as session:
        session.add(PlatformState(id=1, modules_generation=1))
        session.commit()
    assert supervisor.refresh() is True
    assert supervisor.current is not first
    git = supervisor.current._git  # type: ignore[union-attr, attr-defined]
    assert git.settings.forgejo_token.get_secret_value() == "rotated"


def test_no_git_ci_module_falls_back_to_the_pack_files(
    sessions: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(HttpModuleManager, "connections", lambda self: {})
    monkeypatch.setenv("COBBLE_PACK_FORGEJO_TOKEN", "a")
    monkeypatch.setenv("COBBLE_PACK_WOODPECKER_TOKEN", "b")
    supervisor = make_scheduler_supervisor(configured(), sessions, None)
    assert supervisor is not None
    supervisor.refresh()
    assert supervisor.current is not None  # the v0.1 path still works with no module installed


def test_modules_without_an_agent_service_leave_the_scheduler_off(
    sessions: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(HttpModuleManager, "connections", lambda self: CONNECTIONS)
    settings = Settings(run_token_secret="s", module_manager_token="m", agent_service_token="")
    supervisor = make_scheduler_supervisor(settings, sessions, None)
    assert supervisor is not None
    supervisor.refresh()
    assert supervisor.current is None


def test_an_unreachable_manager_keeps_what_runs_and_is_retried(
    sessions: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    answers: list[Any] = [CONNECTIONS, ModuleManagerUnavailable("down"), CONNECTIONS]

    def connections(self: HttpModuleManager) -> Any:
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(HttpModuleManager, "connections", connections)
    supervisor = make_scheduler_supervisor(configured(), sessions, None)
    assert supervisor is not None
    supervisor.refresh()
    running = supervisor.current
    with sessions() as session:
        session.add(PlatformState(id=1, modules_generation=1))
        session.commit()
    assert supervisor.refresh() is False  # manager down: the running scheduler stays
    assert supervisor.current is running
    assert supervisor.refresh() is True  # next time the manager answers, the change is applied
    assert supervisor.current is not running
