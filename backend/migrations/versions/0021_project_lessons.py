"""Per-project lessons learned (ADR 0026)

Revision ID: 0021
Revises: 0020
Create Date: 2026-11-09
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "project_lessons",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "project_id",
            sa.Uuid(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("text", sa.String(300), nullable=False),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("task_ref", sa.String(20), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("hits", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_project_lessons_project_id", "project_lessons", ["project_id"])


def downgrade() -> None:
    op.drop_index("ix_project_lessons_project_id", table_name="project_lessons")
    op.drop_table("project_lessons")
