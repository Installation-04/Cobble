"""Data model of a to-do item."""

from typing import Annotated

from pydantic import BaseModel, StringConstraints

Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class TodoCreate(BaseModel):
    """What a client sends to create a todo."""

    title: Title


class Todo(BaseModel):
    """A stored todo."""

    id: int
    title: Title
    done: bool = False
