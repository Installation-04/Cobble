"""Last seen price of each model

Revision ID: 0014
Revises: 0013
Create Date: 2026-11-04
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "model_prices",
        sa.Column("model", sa.String(200), primary_key=True),
        sa.Column("upstream", sa.String(200), nullable=True),
        sa.Column("prompt_usd", sa.Numeric(20, 12), nullable=False),
        sa.Column("completion_usd", sa.Numeric(20, 12), nullable=False),
        sa.Column("free", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("previous_prompt_usd", sa.Numeric(20, 12), nullable=True),
        sa.Column("previous_completion_usd", sa.Numeric(20, 12), nullable=True),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )


def downgrade() -> None:
    op.drop_table("model_prices")
