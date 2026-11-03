"""First-run wizard state: has the administrator been through the welcome steps?

The wizard itself runs in the browser and only uses routes that already exist (modules, models,
projects). This remembers that it was finished or skipped, so it is offered once.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter

from cobble.db.models import PlatformState

from .deps import AdminUser, Db

router = APIRouter()


def _state(db: Db) -> PlatformState:
    state = db.get(PlatformState, 1)
    if state is None:
        state = PlatformState(id=1)
        db.add(state)
        db.flush()
    return state


@router.get("/setup/progress")
def progress(_admin: AdminUser, db: Db) -> dict[str, bool]:
    state = db.get(PlatformState, 1)
    return {"completed": bool(state and state.setup_completed)}


@router.post("/setup/complete")
def complete(_admin: AdminUser, db: Db) -> dict[str, bool]:
    state = _state(db)
    if not state.setup_completed:
        state.setup_completed = True
        state.setup_completed_at = datetime.now(UTC)
        db.commit()
    return {"completed": True}
