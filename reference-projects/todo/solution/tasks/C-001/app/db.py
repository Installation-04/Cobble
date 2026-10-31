"""Storage of the todos in a SQLite file, so they survive a restart (path: app.config)."""

import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from datetime import date

from app import config
from app.models import Todo

SCHEMA = """
CREATE TABLE IF NOT EXISTS todos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    done INTEGER NOT NULL DEFAULT 0,
    due_date TEXT
)
"""

Row = tuple[int, str, int, str | None]


def _upgrade(conn: sqlite3.Connection) -> None:
    """Add the due date column to a database created before it existed."""
    columns = {row[1] for row in conn.execute("PRAGMA table_info(todos)")}
    if "due_date" not in columns:
        conn.execute("ALTER TABLE todos ADD COLUMN due_date TEXT")


@contextmanager
def _connection() -> Iterator[sqlite3.Connection]:
    """A connection that commits on success; one per call, so threads never share it."""
    path = config.database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as conn:
        conn.execute(SCHEMA)
        _upgrade(conn)
        with conn:
            yield conn


def _todo(row: Row) -> Todo:
    due = date.fromisoformat(row[3]) if row[3] else None
    return Todo(id=row[0], title=row[1], done=bool(row[2]), due_date=due)


def reset() -> None:
    """Forget every todo (tests start from an empty store)."""
    with _connection() as conn:
        conn.execute("DELETE FROM todos")
        conn.execute("DELETE FROM sqlite_sequence WHERE name = 'todos'")


def create_todo(title: str, due_date: date | None = None) -> Todo:
    due = due_date.isoformat() if due_date else None
    with _connection() as conn:
        cursor = conn.execute("INSERT INTO todos (title, due_date) VALUES (?, ?)", (title, due))
        todo_id = cursor.lastrowid
    if todo_id is None:
        raise RuntimeError("the database did not return the new id")
    return Todo(id=todo_id, title=title, due_date=due_date)


def list_todos() -> list[Todo]:
    """All todos, oldest first."""
    with _connection() as conn:
        rows = conn.execute("SELECT id, title, done, due_date FROM todos ORDER BY id").fetchall()
    return [_todo(row) for row in rows]


def get_todo(todo_id: int) -> Todo | None:
    with _connection() as conn:
        row = conn.execute(
            "SELECT id, title, done, due_date FROM todos WHERE id = ?", (todo_id,)
        ).fetchone()
    return None if row is None else _todo(row)


def set_done(todo_id: int, done: bool) -> Todo | None:
    with _connection() as conn:
        conn.execute("UPDATE todos SET done = ? WHERE id = ?", (int(done), todo_id))
    return get_todo(todo_id)


def delete_todo(todo_id: int) -> bool:
    with _connection() as conn:
        cursor = conn.execute("DELETE FROM todos WHERE id = ?", (todo_id,))
    return cursor.rowcount > 0
