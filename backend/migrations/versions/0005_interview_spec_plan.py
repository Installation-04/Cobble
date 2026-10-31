"""Interview, spec and plan: project phase, messages, specs and plans

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-31
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def _id_and_project() -> list[sa.Column[object]]:
    return [
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "project_id",
            sa.Uuid(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
    ]


def _created_at() -> sa.Column[object]:
    return sa.Column(
        "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column("phase", sa.String(20), nullable=False, server_default="interview"),
    )

    op.create_table(
        "messages",
        *_id_and_project(),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        _created_at(),
    )
    op.create_index("ix_messages_project_id", "messages", ["project_id"])

    op.create_table(
        "specs",
        *_id_and_project(),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        _created_at(),
        sa.UniqueConstraint("project_id", "version"),
    )
    op.create_index("ix_specs_project_id", "specs", ["project_id"])

    op.create_table(
        "plans",
        *_id_and_project(),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("plan", sa.JSON(), nullable=False),
        sa.Column("estimate", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        _created_at(),
        sa.UniqueConstraint("project_id", "version"),
    )
    op.create_index("ix_plans_project_id", "plans", ["project_id"])


def downgrade() -> None:
    op.drop_index("ix_plans_project_id", table_name="plans")
    op.drop_table("plans")
    op.drop_index("ix_specs_project_id", table_name="specs")
    op.drop_table("specs")
    op.drop_index("ix_messages_project_id", table_name="messages")
    op.drop_table("messages")
    op.drop_column("projects", "phase")
