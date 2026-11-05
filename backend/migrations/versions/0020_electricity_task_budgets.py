"""Electricity of local models and the per-task budget settings

Revision ID: 0020
Revises: 0015
Create Date: 2026-11-04
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0020"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("llm_calls", sa.Column("duration_ms", sa.Integer(), nullable=True))
    op.add_column("llm_calls", sa.Column("electricity_usd", sa.Numeric(14, 8), nullable=True))
    op.add_column(
        "platform_state", sa.Column("electricity_price_kwh_usd", sa.Numeric(12, 6), nullable=True)
    )
    op.add_column("platform_state", sa.Column("electricity_watts", sa.Integer(), nullable=True))
    op.add_column(
        "platform_state",
        sa.Column(
            "electricity_counts_in_budget",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "platform_state", sa.Column("task_budget_multiplier", sa.Numeric(8, 2), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("platform_state", "task_budget_multiplier")
    op.drop_column("platform_state", "electricity_counts_in_budget")
    op.drop_column("platform_state", "electricity_watts")
    op.drop_column("platform_state", "electricity_price_kwh_usd")
    op.drop_column("llm_calls", "electricity_usd")
    op.drop_column("llm_calls", "duration_ms")
