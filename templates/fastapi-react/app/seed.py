"""Demo data. Cobble asks an agent to rewrite `seed()` at the end of each milestone.

Contract: `seed()` runs once, when the demo container starts for the first time (see
`app/serve.py`). It must be idempotent (insert only when the tables are empty), need no network
and no secret, and fill the app with realistic, varied data: plausible names, dates and
quantities; never lorem ipsum, never an empty screen. Write under `COBBLE_DATA_DIR`
(the demo's root filesystem is read-only).
"""

from __future__ import annotations


def seed() -> None:
    """Nothing to seed yet: the template has no data model."""
