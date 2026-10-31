"""Milestones and demo: the milestones table and the kind of a task

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-31
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tasks", sa.Column("kind", sa.String(10), nullable=False, server_default="plan"))
    op.create_table(
        "milestones",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "project_id",
            sa.Uuid(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("ref", sa.String(20), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("tag", sa.String(100), nullable=True),
        sa.Column("preview_path", sa.Text(), nullable=True),
        sa.Column("preview_state", sa.String(20), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("built_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("validated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("project_id", "ref"),
    )
    op.create_index("ix_milestones_project_id", "milestones", ["project_id"])


def downgrade() -> None:
    op.drop_index("ix_milestones_project_id", table_name="milestones")
    op.drop_table("milestones")
    op.drop_column("tasks", "kind")
