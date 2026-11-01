"""The first-run wizard remembers that it was finished, for administrators only."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session, sessionmaker

from cobble.db.models import PlatformState

from .test_models_api import Built
from .test_modules_api import H

PROGRESS = "/api/v1/setup/progress"
COMPLETE = "/api/v1/setup/complete"


def test_the_wizard_is_offered_until_it_is_completed(
    sessions: sessionmaker[Session],
) -> None:
    b = Built(sessions)
    assert b.api.get(PROGRESS).json() == {"completed": False}
    assert b.api.post(COMPLETE, headers=H).json() == {"completed": True}
    assert b.api.get(PROGRESS).json() == {"completed": True}
    # completing again changes nothing, in particular not the date
    with sessions() as s:
        first = s.get(PlatformState, 1).setup_completed_at  # type: ignore[union-attr]
    b.api.post(COMPLETE, headers=H)
    with sessions() as s:
        assert s.get(PlatformState, 1).setup_completed_at == first  # type: ignore[union-attr]


@pytest.mark.parametrize(("method", "path"), [("GET", PROGRESS), ("POST", COMPLETE)])
def test_only_administrators_and_only_with_csrf(
    sessions: sessionmaker[Session], method: str, path: str
) -> None:
    b = Built(sessions)
    if method == "POST":
        assert b.api.post(path).status_code == 403  # no CSRF header
    b.api.cookies.clear()
    assert b.api.request(method, path, headers=H).status_code == 401
    b.stack.login(b.api, role="member")
    reply = b.api.request(method, path, headers=H)
    assert reply.status_code == 403 and reply.json()["error"]["code"] == "forbidden"
    with sessions() as s:
        state = s.get(PlatformState, 1)
        assert state is None or not state.setup_completed
