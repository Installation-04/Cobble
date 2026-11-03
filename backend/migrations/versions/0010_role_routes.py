"""Per-role model routes with fallback chains

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-03
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("platform_state", sa.Column("role_routes", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("platform_state", "role_routes")
