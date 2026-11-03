"""Record which model a call fell back from

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-03
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("llm_calls", sa.Column("fallback_from", sa.String(200), nullable=True))
    op.add_column(
        "llm_calls", sa.Column("fallbacks", sa.Integer(), nullable=False, server_default="0")
    )


def downgrade() -> None:
    op.drop_column("llm_calls", "fallbacks")
    op.drop_column("llm_calls", "fallback_from")
