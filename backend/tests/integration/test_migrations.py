from __future__ import annotations

import pytest
from alembic import command
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

from .conftest import alembic_config

pytestmark = pytest.mark.integration


def tables(url: str) -> set[str]:
    engine = create_engine(url)
    try:
        return set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


def test_upgrade_then_downgrade_then_upgrade(database_url: str) -> None:
    config = alembic_config(database_url)
    command.downgrade(config, "base")
    assert "llm_calls" not in tables(database_url)

    command.upgrade(config, "head")
    assert "llm_calls" in tables(database_url)
    engine = create_engine(database_url)
    try:
        columns = {c["name"] for c in inspect(engine).get_columns("llm_calls")}
    finally:
        engine.dispose()
    assert {"prompt_tokens", "completion_tokens", "cost_usd", "project_id", "task_id"} <= columns

    command.downgrade(config, "base")
    assert "llm_calls" not in tables(database_url)

    command.upgrade(config, "head")
    assert "llm_calls" in tables(database_url)


STEP3_TABLES = {"users", "auth_sessions", "activation_tokens", "folders", "projects"}


def test_migration_0002_up_and_down(database_url: str) -> None:
    config = alembic_config(database_url)
    command.downgrade(config, "base")
    command.upgrade(config, "0001")
    assert not STEP3_TABLES & tables(database_url)

    command.upgrade(config, "0002")
    assert tables(database_url) >= STEP3_TABLES
    engine = create_engine(database_url)
    try:
        inspector = inspect(engine)
        assert {"email", "password_hash", "role", "lang", "theme", "created_at"} <= {
            c["name"] for c in inspector.get_columns("users")
        }
        assert {"folder_id", "owner_id"} <= {c["name"] for c in inspector.get_columns("projects")}
        fks = inspector.get_foreign_keys("projects")
        folder_fk = next(fk for fk in fks if fk["referred_table"] == "folders")
        assert folder_fk["options"].get("ondelete") == "SET NULL"
    finally:
        engine.dispose()

    command.downgrade(config, "0001")
    remaining = tables(database_url)
    assert not STEP3_TABLES & remaining
    assert "llm_calls" in remaining

    command.upgrade(config, "head")
    assert tables(database_url) >= STEP3_TABLES


def test_0003_adds_and_removes_project_budget_columns(database_url: str) -> None:
    config = alembic_config(database_url)
    command.upgrade(config, "head")
    engine = create_engine(database_url)
    try:
        columns = {c["name"] for c in inspect(engine).get_columns("projects")}
        assert {"budget_usd", "status", "budget_warning_sent"} <= columns

        command.downgrade(config, "0002")
        columns = {c["name"] for c in inspect(engine).get_columns("projects")}
        assert not {"budget_usd", "status", "budget_warning_sent"} & columns
    finally:
        engine.dispose()
    command.upgrade(config, "head")


STEP5_TABLES = {"messages", "specs", "plans"}


def test_migration_0005_up_and_down(database_url: str) -> None:
    config = alembic_config(database_url)
    command.downgrade(config, "0004")
    engine = create_engine(database_url)
    try:
        assert not STEP5_TABLES & tables(database_url)
        assert "phase" not in {c["name"] for c in inspect(engine).get_columns("projects")}
        # A project that exists before the migration lands in the interview phase.
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO users (id, email, password_hash) "
                    "VALUES ('00000000-0000-0000-0000-000000000001', 'm@example.com', 'x')"
                )
            )
            conn.execute(
                text(
                    "INSERT INTO projects (id, owner_id, name) VALUES "
                    "('00000000-0000-0000-0000-0000000000a1', "
                    "'00000000-0000-0000-0000-000000000001', 'old')"
                )
            )

        command.upgrade(config, "0005")
        inspector = inspect(engine)
        assert tables(database_url) >= STEP5_TABLES
        assert "phase" in {c["name"] for c in inspector.get_columns("projects")}
        for table, columns in {
            "messages": {"id", "project_id", "role", "content", "created_at"},
            "specs": {"id", "project_id", "version", "content", "status", "created_at"},
            "plans": {"id", "project_id", "version", "plan", "estimate", "status", "created_at"},
        }.items():
            assert columns <= {c["name"] for c in inspector.get_columns(table)}
            fks = inspector.get_foreign_keys(table)
            assert fks[0]["referred_table"] == "projects"
            assert fks[0]["options"].get("ondelete") == "CASCADE"
        for table in ("specs", "plans"):
            uniques = inspector.get_unique_constraints(table)
            assert any(set(u["column_names"]) == {"project_id", "version"} for u in uniques)

        with engine.begin() as conn:
            phase = conn.execute(text("SELECT phase FROM projects")).scalar_one()
            assert phase == "interview"
            conn.execute(
                text(
                    "INSERT INTO specs (id, project_id, version, content) VALUES "
                    "('00000000-0000-0000-0000-0000000000b1', "
                    "'00000000-0000-0000-0000-0000000000a1', 1, '# spec')"
                )
            )
            assert conn.execute(text("SELECT status FROM specs")).scalar_one() == "draft"
            conn.execute(text("DELETE FROM projects"))  # cascades
            assert conn.execute(text("SELECT count(*) FROM specs")).scalar_one() == 0
            conn.execute(text("DELETE FROM users"))

        command.downgrade(config, "0004")
        assert not STEP5_TABLES & tables(database_url)
        assert "phase" not in {c["name"] for c in inspect(engine).get_columns("projects")}
    finally:
        engine.dispose()
    command.upgrade(config, "head")
    assert tables(database_url) >= STEP5_TABLES


STEP7_TABLES = {"tasks", "task_runs"}


def test_migration_0006_up_and_down(database_url: str) -> None:
    config = alembic_config(database_url)
    command.downgrade(config, "0005")
    engine = create_engine(database_url)
    try:
        assert not STEP7_TABLES & tables(database_url)
        project_columns = {c["name"] for c in inspect(engine).get_columns("projects")}
        assert not {"repo_name", "repo_clone_url"} & project_columns
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO users (id, email, password_hash) "
                    "VALUES ('00000000-0000-0000-0000-000000000001', 'm@example.com', 'x')"
                )
            )
            conn.execute(
                text(
                    "INSERT INTO projects (id, owner_id, name, phase) VALUES "
                    "('00000000-0000-0000-0000-0000000000a1', "
                    "'00000000-0000-0000-0000-000000000001', 'old', 'ready')"
                )
            )

        command.upgrade(config, "0006")
        inspector = inspect(engine)
        assert tables(database_url) >= STEP7_TABLES
        assert {"repo_name", "repo_clone_url"} <= {
            c["name"] for c in inspector.get_columns("projects")
        }
        assert {
            "id",
            "project_id",
            "ref",
            "title",
            "milestone",
            "depends_on",
            "files",
            "acceptance",
            "tests",
            "size",
            "role",
            "state",
            "attempts",
            "escalated",
            "branch",
            "pr_number",
            "last_error",
            "created_at",
            "updated_at",
        } <= {c["name"] for c in inspector.get_columns("tasks")}
        assert {
            "id",
            "task_id",
            "kind",
            "attempt",
            "model",
            "state",
            "agent_run_id",
            "iterations",
            "head_sha",
            "started_at",
            "finished_at",
            "log_tail",
        } <= {c["name"] for c in inspector.get_columns("task_runs")}
        for table, parent in (("tasks", "projects"), ("task_runs", "tasks")):
            fk = inspector.get_foreign_keys(table)[0]
            assert fk["referred_table"] == parent
            assert fk["options"].get("ondelete") == "CASCADE"
        uniques = inspector.get_unique_constraints("tasks")
        assert any(set(u["column_names"]) == {"project_id", "ref"} for u in uniques)

        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO tasks (id, project_id, ref, title, milestone, depends_on, files, "
                    "acceptance, tests, size, role) VALUES "
                    "('00000000-0000-0000-0000-0000000000c1', "
                    "'00000000-0000-0000-0000-0000000000a1', 'T-001', 't', 'M1', '[]', '[]', '[]', "
                    "'tests/a.py', 'S', 'backend')"
                )
            )
            row = conn.execute(text("SELECT state, attempts, escalated FROM tasks")).one()
            assert tuple(row) == ("todo", 0, False)
            conn.execute(
                text(
                    "INSERT INTO task_runs (id, task_id, kind, attempt, model, state) VALUES "
                    "('00000000-0000-0000-0000-0000000000d1', "
                    "'00000000-0000-0000-0000-0000000000c1', 'worker', 1, 'm', 'running')"
                )
            )
            assert conn.execute(text("SELECT iterations FROM task_runs")).scalar_one() == 0
        with pytest.raises(IntegrityError), engine.begin() as conn:  # (project_id, ref) is unique
            conn.execute(
                text(
                    "INSERT INTO tasks (id, project_id, ref, title, milestone, depends_on, "
                    "files, acceptance, tests, size, role) VALUES "
                    "('00000000-0000-0000-0000-0000000000c2', "
                    "'00000000-0000-0000-0000-0000000000a1', 'T-001', 't', 'M1', '[]', '[]', "
                    "'[]', 'x', 'S', 'backend')"
                )
            )
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM projects"))  # cascades to tasks and runs
            assert conn.execute(text("SELECT count(*) FROM task_runs")).scalar_one() == 0
            assert conn.execute(text("SELECT count(*) FROM tasks")).scalar_one() == 0
            conn.execute(text("DELETE FROM users"))

        command.downgrade(config, "0005")
        assert not STEP7_TABLES & tables(database_url)
        assert not {"repo_name", "repo_clone_url"} & {
            c["name"] for c in inspect(engine).get_columns("projects")
        }
    finally:
        engine.dispose()
    command.upgrade(config, "head")
    assert tables(database_url) >= STEP7_TABLES
