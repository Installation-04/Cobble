"""Modules: installed modules, their secrets, links and event history, and the platform state

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-01
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "modules",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("version", sa.String(40), nullable=False),
        sa.Column("variant", sa.String(20), nullable=True),
        sa.Column("explicit", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("state", sa.String(20), nullable=False, server_default="installing"),
        sa.Column("settings", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("last_error", sa.String(100), nullable=True),
        sa.Column(
            "installed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_table(
        "module_secrets",
        sa.Column(
            "module_id",
            sa.String(40),
            sa.ForeignKey("modules.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("key", sa.String(40), primary_key=True),
        sa.Column("ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("nonce", sa.LargeBinary(), nullable=False),
        sa.Column("key_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_table(
        "module_links",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "consumer",
            sa.String(40),
            sa.ForeignKey("modules.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "provider",
            sa.String(40),
            sa.ForeignKey("modules.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("capability", sa.String(40), nullable=False),
        sa.Column("state", sa.String(20), nullable=False, server_default="pending"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("consumer", "provider", "capability"),
    )
    op.create_index("ix_module_links_consumer", "module_links", ["consumer"])
    op.create_index("ix_module_links_provider", "module_links", ["provider"])
    op.create_table(
        "module_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("module_id", sa.String(40), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("step", sa.String(30), nullable=True),
        sa.Column("outcome", sa.String(10), nullable=False, server_default="ok"),
        sa.Column("code", sa.String(100), nullable=True),
        sa.Column("params", sa.JSON(), nullable=False, server_default="{}"),
    )
    op.create_index("ix_module_events_module_id", "module_events", ["module_id"])
    op.create_table(
        "platform_state",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("setup_completed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("setup_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("modules_generation", sa.Integer(), nullable=False, server_default="0"),
        sa.CheckConstraint("id = 1", name="ck_platform_state_single_row"),
    )
    # The single row exists from the start, so readers never have to create it.
    op.execute("INSERT INTO platform_state (id) VALUES (1)")


def downgrade() -> None:
    op.drop_table("platform_state")
    op.drop_index("ix_module_events_module_id", table_name="module_events")
    op.drop_table("module_events")
    op.drop_index("ix_module_links_provider", table_name="module_links")
    op.drop_index("ix_module_links_consumer", table_name="module_links")
    op.drop_table("module_links")
    op.drop_table("module_secrets")
    op.drop_table("modules")
