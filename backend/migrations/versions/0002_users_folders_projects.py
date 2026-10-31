"""Create users, auth_sessions, activation_tokens, folders, projects

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-31
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def _created_at() -> sa.Column[sa.DateTime]:
    return sa.Column(
        "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("email", sa.String(254), nullable=False),
        sa.Column("password_hash", sa.String(500), nullable=False),
        sa.Column("role", sa.String(20), server_default="admin", nullable=False),
        sa.Column("lang", sa.String(5), server_default="en", nullable=False),
        sa.Column("theme", sa.String(10), server_default="system", nullable=False),
        _created_at(),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )
    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        _created_at(),
        sa.UniqueConstraint("token_hash", name="uq_auth_sessions_token_hash"),
    )
    op.create_index("ix_auth_sessions_user_id", "auth_sessions", ["user_id"])
    op.create_table(
        "activation_tokens",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True)),
        _created_at(),
        sa.UniqueConstraint("token_hash", name="uq_activation_tokens_token_hash"),
    )
    op.create_table(
        "folders",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "owner_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        _created_at(),
    )
    op.create_index("ix_folders_owner_id", "folders", ["owner_id"])
    op.create_table(
        "projects",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "owner_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("folder_id", sa.Uuid(), sa.ForeignKey("folders.id", ondelete="SET NULL")),
        _created_at(),
    )
    op.create_index("ix_projects_owner_id", "projects", ["owner_id"])
    op.create_index("ix_projects_folder_id", "projects", ["folder_id"])


def downgrade() -> None:
    op.drop_index("ix_projects_folder_id", table_name="projects")
    op.drop_index("ix_projects_owner_id", table_name="projects")
    op.drop_table("projects")
    op.drop_index("ix_folders_owner_id", table_name="folders")
    op.drop_table("folders")
    op.drop_table("activation_tokens")
    op.drop_index("ix_auth_sessions_user_id", table_name="auth_sessions")
    op.drop_table("auth_sessions")
    op.drop_table("users")
