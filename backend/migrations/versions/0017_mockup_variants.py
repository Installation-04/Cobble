"""Mockup variants proposed by the planner, and the per-project switch

Revision ID: 0017
Revises: 0016
Create Date: 2026-11-04
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column("mockups_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_table(
        "mockup_variants",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "project_id",
            sa.Uuid(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(120), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("wireframe", sa.Text(), nullable=False),
        sa.Column("chosen", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("project_id", "position"),
    )
    op.create_index("ix_mockup_variants_project_id", "mockup_variants", ["project_id"])


def downgrade() -> None:
    op.drop_index("ix_mockup_variants_project_id", table_name="mockup_variants")
    op.drop_table("mockup_variants")
    op.drop_column("projects", "mockups_enabled")
