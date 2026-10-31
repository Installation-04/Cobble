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
