from __future__ import annotations

import logging

import pytest
from sqlalchemy.orm import Session, sessionmaker

from cobble.config import Settings
from cobble.scheduler.factory import build_scheduler, make_scheduler_supervisor


def test_no_run_token_secret_disables_the_scheduler(
    sessions: sessionmaker[Session], caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING):
        settings = Settings(run_token_secret="", module_manager_token="m")
        assert make_scheduler_supervisor(settings, sessions, None) is None
    assert "COBBLE_RUN_TOKEN_SECRET" in caplog.text


def test_without_the_fake_pack_or_a_manager_token_there_is_no_scheduler(
    sessions: sessionmaker[Session], caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING):
        assert build_scheduler(Settings(run_token_secret="s"), sessions, None) is None
    assert "install the modules" in caplog.text


def test_the_fake_pack_builds_a_scheduler_on_fakes(sessions: sessionmaker[Session]) -> None:
    assert build_scheduler(Settings(pack_mode="fake"), sessions, None) is not None


# --- following the installed modules ----------------------------------------------------------

from typing import Any  # noqa: E402

from cobble.db.models import PlatformState  # noqa: E402
from cobble.providers.module_manager import (  # noqa: E402
    HttpModuleManager,
    ModuleManagerUnavailable,
)

CONNECTIONS = {
    "forgejo": {"url": "http://forgejo:3000", "provides": ["git"], "secrets": {"api_token": "g"}},
    "woodpecker": {
        "url": "http://woodpecker-server:8000",
        "provides": ["ci"],
        "secrets": {"api_token": "c"},
    },
    "aider": {
        "url": "http://cobble-aider-agent-service:8090",
        "provides": ["agent-runner"],
        "secrets": {"service_token": "a"},
    },
    "preview": {
        "url": "http://cobble-preview-preview-service:8091",
        "provides": ["preview"],
        "secrets": {"service_token": "p"},
    },
}


def configured(**extra: Any) -> Settings:
    return Settings(run_token_secret="s", module_manager_token="m", **extra)


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
    assert scheduler._agents is not None  # type: ignore[attr-defined]
    assert scheduler._preview is not None  # type: ignore[attr-defined]


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


def test_no_git_ci_module_leaves_the_scheduler_off(
    sessions: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(HttpModuleManager, "connections", lambda self: {})
    supervisor = make_scheduler_supervisor(configured(), sessions, None)
    assert supervisor is not None
    supervisor.refresh()
    assert supervisor.current is None  # planning still works; building waits for the modules


def test_modules_without_an_agent_module_leave_the_scheduler_off(
    sessions: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    without = {k: v for k, v in CONNECTIONS.items() if k != "aider"}
    monkeypatch.setattr(HttpModuleManager, "connections", lambda self: without)
    supervisor = make_scheduler_supervisor(configured(), sessions, None)
    assert supervisor is not None
    supervisor.refresh()
    assert supervisor.current is None


def test_the_preview_module_is_optional(
    sessions: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    without = {k: v for k, v in CONNECTIONS.items() if k != "preview"}
    monkeypatch.setattr(HttpModuleManager, "connections", lambda self: without)
    supervisor = make_scheduler_supervisor(configured(), sessions, None)
    assert supervisor is not None
    supervisor.refresh()
    assert supervisor.current is not None
    assert supervisor.current._preview is None  # type: ignore[attr-defined]


def test_the_agent_module_gets_its_address_and_token_from_the_connection(
    sessions: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(HttpModuleManager, "connections", lambda self: CONNECTIONS)
    supervisor = make_scheduler_supervisor(configured(), sessions, None)
    assert supervisor is not None
    supervisor.refresh()
    agents = supervisor.current._agents  # type: ignore[union-attr, attr-defined]
    assert str(agents._client.base_url) == "http://cobble-aider-agent-service:8090"
    assert agents._client.headers["authorization"] == "Bearer a"


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
