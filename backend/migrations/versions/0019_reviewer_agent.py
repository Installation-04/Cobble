"""Reviewer agent: the per-project switch and the stored verdict of a task

Revision ID: 0019
Revises: 0018
Create Date: 2026-11-09
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column("review_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("tasks", sa.Column("review", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("tasks", "review")
    op.drop_column("projects", "review_enabled")
