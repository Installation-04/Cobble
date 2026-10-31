"""Storage of the todos. Kept in memory for now (the persistence task moves it to a file)."""

import threading

from app.models import Todo


class _Store:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.todos: dict[int, Todo] = {}
        self.last_id = 0


_store = _Store()


def reset() -> None:
    """Forget every todo (tests start from an empty store)."""
    with _store.lock:
        _store.todos.clear()
        _store.last_id = 0


def create_todo(title: str) -> Todo:
    with _store.lock:
        _store.last_id += 1
        todo = Todo(id=_store.last_id, title=title)
        _store.todos[todo.id] = todo
        return todo


def list_todos() -> list[Todo]:
    """All todos, oldest first."""
    with _store.lock:
        return [_store.todos[todo_id] for todo_id in sorted(_store.todos)]


def get_todo(todo_id: int) -> Todo | None:
    with _store.lock:
        return _store.todos.get(todo_id)


def set_done(todo_id: int, done: bool) -> Todo | None:
    with _store.lock:
        todo = _store.todos.get(todo_id)
        if todo is None:
            return None
        updated = todo.model_copy(update={"done": done})
        _store.todos[todo_id] = updated
        return updated


def delete_todo(todo_id: int) -> bool:
    with _store.lock:
        return _store.todos.pop(todo_id, None) is not None
