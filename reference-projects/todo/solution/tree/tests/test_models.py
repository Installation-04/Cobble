import pytest
from pydantic import ValidationError

from app import db
from app.models import Todo, TodoCreate


@pytest.fixture(autouse=True)
def fresh_db() -> None:
    db.reset()


def test_a_todo_is_not_done_by_default() -> None:
    assert Todo(id=1, title="Buy milk").done is False


def test_a_todo_has_an_id_a_title_and_a_done_flag() -> None:
    todo = Todo(id=3, title="Call the dentist", done=True)
    assert (todo.id, todo.title, todo.done) == (3, "Call the dentist", True)


def test_a_title_has_one_to_two_hundred_characters() -> None:
    with pytest.raises(ValidationError):
        TodoCreate(title="")
    with pytest.raises(ValidationError):
        TodoCreate(title="x" * 201)
    assert TodoCreate(title="x" * 200).title == "x" * 200


def test_a_stored_todo_can_be_read_back_with_the_same_values() -> None:
    created = db.create_todo("Call the dentist")
    assert created.title == "Call the dentist"
    assert created.done is False
    assert db.get_todo(created.id) == created
    assert db.list_todos() == [created]


def test_stored_todos_get_distinct_ids_and_keep_their_order() -> None:
    first = db.create_todo("first")
    second = db.create_todo("second")
    assert first.id != second.id
    assert [todo.title for todo in db.list_todos()] == ["first", "second"]


def test_a_stored_todo_can_be_marked_done_and_deleted() -> None:
    created = db.create_todo("Water the plants")
    done = db.set_done(created.id, True)
    assert done is not None
    assert done.done is True
    assert db.delete_todo(created.id) is True
    assert db.get_todo(created.id) is None
    assert db.delete_todo(created.id) is False
