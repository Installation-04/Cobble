"""Storage of the todos in a SQLite file, so they survive a restart (path: app.config)."""

import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager

from app import config
from app.models import Todo

SCHEMA = """
CREATE TABLE IF NOT EXISTS todos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    done INTEGER NOT NULL DEFAULT 0
)
"""

Row = tuple[int, str, int]


@contextmanager
def _connection() -> Iterator[sqlite3.Connection]:
    """A connection that commits on success; one per call, so threads never share it."""
    path = config.database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as conn:
        conn.execute(SCHEMA)
        with conn:
            yield conn


def _todo(row: Row) -> Todo:
    return Todo(id=row[0], title=row[1], done=bool(row[2]))


def reset() -> None:
    """Forget every todo (tests start from an empty store)."""
    with _connection() as conn:
        conn.execute("DELETE FROM todos")
        conn.execute("DELETE FROM sqlite_sequence WHERE name = 'todos'")


def create_todo(title: str) -> Todo:
    with _connection() as conn:
        cursor = conn.execute("INSERT INTO todos (title) VALUES (?)", (title,))
        todo_id = cursor.lastrowid
    if todo_id is None:
        raise RuntimeError("the database did not return the new id")
    return Todo(id=todo_id, title=title)


def list_todos() -> list[Todo]:
    """All todos, oldest first."""
    with _connection() as conn:
        rows = conn.execute("SELECT id, title, done FROM todos ORDER BY id").fetchall()
    return [_todo(row) for row in rows]


def get_todo(todo_id: int) -> Todo | None:
    with _connection() as conn:
        row = conn.execute("SELECT id, title, done FROM todos WHERE id = ?", (todo_id,)).fetchone()
    return None if row is None else _todo(row)


def set_done(todo_id: int, done: bool) -> Todo | None:
    with _connection() as conn:
        conn.execute("UPDATE todos SET done = ? WHERE id = ?", (int(done), todo_id))
    return get_todo(todo_id)


def delete_todo(todo_id: int) -> bool:
    with _connection() as conn:
        cursor = conn.execute("DELETE FROM todos WHERE id = ?", (todo_id,))
    return cursor.rowcount > 0
