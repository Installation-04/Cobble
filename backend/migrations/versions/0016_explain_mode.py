"""Explain mode: a per-project switch and the summary stored on each milestone

Revision ID: 0016
Revises: 0015
Create Date: 2026-11-04
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column("explain_mode", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("milestones", sa.Column("explanation", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("milestones", "explanation")
    op.drop_column("projects", "explain_mode")
