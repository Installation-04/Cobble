"""Questions an agent asks the user (ADR 0025)

Revision ID: 0020
Revises: 0018
Create Date: 2026-11-09
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0020"
# 0019 belongs to a parallel branch of work; the merge puts this migration after it.
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "task_questions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "task_id", sa.Uuid(), sa.ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "run_id", sa.Uuid(), sa.ForeignKey("task_runs.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("choices", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(10), nullable=False, server_default="open"),
        sa.Column("answer", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("answered_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_task_questions_task_id", "task_questions", ["task_id"])


def downgrade() -> None:
    op.drop_index("ix_task_questions_task_id", table_name="task_questions")
    op.drop_table("task_questions")
