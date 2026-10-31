from __future__ import annotations

import pytest
from alembic import command
from sqlalchemy import create_engine, inspect

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
