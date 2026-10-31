"""Scheduler: tasks, task runs and the project's repository

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-31
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("projects", sa.Column("repo_name", sa.String(200), nullable=True))
    op.add_column("projects", sa.Column("repo_clone_url", sa.Text(), nullable=True))

    op.create_table(
        "tasks",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "project_id",
            sa.Uuid(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("ref", sa.String(20), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("milestone", sa.String(20), nullable=False),
        sa.Column("depends_on", sa.JSON(), nullable=False),
        sa.Column("files", sa.JSON(), nullable=False),
        sa.Column("acceptance", sa.JSON(), nullable=False),
        sa.Column("tests", sa.Text(), nullable=False),
        sa.Column("size", sa.String(5), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("state", sa.String(20), nullable=False, server_default="todo"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("escalated", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("branch", sa.String(200), nullable=True),
        sa.Column("pr_number", sa.Integer(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("project_id", "ref"),
    )
    op.create_index("ix_tasks_project_id", "tasks", ["project_id"])

    op.create_table(
        "task_runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "task_id",
            sa.Uuid(),
            sa.ForeignKey("tasks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("model", sa.String(200), nullable=False),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("agent_run_id", sa.String(200), nullable=True),
        sa.Column("iterations", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("head_sha", sa.String(100), nullable=True),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("log_tail", sa.Text(), nullable=True),
    )
    op.create_index("ix_task_runs_task_id", "task_runs", ["task_id"])


def downgrade() -> None:
    op.drop_index("ix_task_runs_task_id", table_name="task_runs")
    op.drop_table("task_runs")
    op.drop_index("ix_tasks_project_id", table_name="tasks")
    op.drop_table("tasks")
    op.drop_column("projects", "repo_clone_url")
    op.drop_column("projects", "repo_name")
