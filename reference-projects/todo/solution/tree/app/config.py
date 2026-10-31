"""Settings read from the environment."""

import os
from pathlib import Path

DEFAULT_DATABASE = "data/todos.db"


def database_path() -> Path:
    """Where the todos are stored: the TODO_DB environment variable, else data/todos.db."""
    return Path(os.environ.get("TODO_DB", DEFAULT_DATABASE))
