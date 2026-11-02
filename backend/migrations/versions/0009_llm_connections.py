"""Model connections (encrypted API keys) and the platform's default model

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-01
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "llm_connections",
        sa.Column("name", sa.String(40), primary_key=True),
        sa.Column("provider", sa.String(20), nullable=False),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("base_url", sa.String(300), nullable=True),
        sa.Column("ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("nonce", sa.LargeBinary(), nullable=False),
        sa.Column("key_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.add_column("platform_state", sa.Column("default_model", sa.String(40), nullable=True))


def downgrade() -> None:
    op.drop_column("platform_state", "default_model")
    op.drop_table("llm_connections")
