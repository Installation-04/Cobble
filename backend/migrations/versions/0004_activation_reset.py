"""Let an activation token target an existing user (admin reset)

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-31
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "activation_tokens",
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE")),
    )


def downgrade() -> None:
    op.drop_column("activation_tokens", "user_id")
