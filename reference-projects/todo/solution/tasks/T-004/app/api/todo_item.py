"""Update and delete one todo."""

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel

from app import db
from app.models import Todo

router = APIRouter(prefix="/api/todos", tags=["todos"])


class TodoUpdate(BaseModel):
    done: bool


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="Todo not found")


@router.patch("/{todo_id}")
def update_todo(todo_id: int, payload: TodoUpdate) -> Todo:
    todo = db.set_done(todo_id, payload.done)
    if todo is None:
        raise _not_found()
    return todo


@router.delete("/{todo_id}", status_code=204)
def delete_todo(todo_id: int) -> Response:
    if not db.delete_todo(todo_id):
        raise _not_found()
    return Response(status_code=204)
