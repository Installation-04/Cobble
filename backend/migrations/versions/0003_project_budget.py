"""Add budget, status and warning flag to projects

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-31
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("projects", sa.Column("budget_usd", sa.Numeric(14, 2)))
    op.add_column(
        "projects",
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
    )
    op.add_column(
        "projects",
        sa.Column("budget_warning_sent", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("projects", "budget_warning_sent")
    op.drop_column("projects", "status")
    op.drop_column("projects", "budget_usd")
