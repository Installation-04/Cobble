"""Create llm_calls

Revision ID: 0001
Revises:
Create Date: 2026-10-31
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "llm_calls",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("model", sa.String(200), nullable=False),
        sa.Column("role", sa.String(50)),
        sa.Column("project_id", sa.Uuid()),
        sa.Column("task_id", sa.Uuid()),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False),
        sa.Column("completion_tokens", sa.Integer(), nullable=False),
        sa.Column("cost_usd", sa.Numeric(14, 8), nullable=False),
        sa.Column("request_id", sa.String(200)),
    )
    op.create_index("ix_llm_calls_project_id", "llm_calls", ["project_id"])
    op.create_index("ix_llm_calls_task_id", "llm_calls", ["task_id"])


def downgrade() -> None:
    op.drop_index("ix_llm_calls_task_id", table_name="llm_calls")
    op.drop_index("ix_llm_calls_project_id", table_name="llm_calls")
    op.drop_table("llm_calls")
