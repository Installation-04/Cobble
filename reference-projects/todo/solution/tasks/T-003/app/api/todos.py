"""Create and list todos."""

from fastapi import APIRouter

from app import db
from app.models import Todo, TodoCreate

router = APIRouter(prefix="/api/todos", tags=["todos"])


@router.post("", status_code=201)
def create_todo(payload: TodoCreate) -> Todo:
    return db.create_todo(payload.title)


@router.get("")
def list_todos() -> list[Todo]:
    """All todos, oldest first."""
    return db.list_todos()
