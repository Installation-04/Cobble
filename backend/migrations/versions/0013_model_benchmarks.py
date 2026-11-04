"""Results of the local model benchmark

Revision ID: 0013
Revises: 0012
Create Date: 2026-11-04
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "model_benchmarks",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("model", sa.String(200), nullable=False, index=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("quality", sa.Numeric(5, 4), nullable=False),
        sa.Column("seconds", sa.Numeric(10, 2), nullable=False),
        sa.Column("tokens_per_second", sa.Numeric(10, 2), nullable=True),
        sa.Column("outcomes", sa.JSON(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )


def downgrade() -> None:
    op.drop_table("model_benchmarks")
