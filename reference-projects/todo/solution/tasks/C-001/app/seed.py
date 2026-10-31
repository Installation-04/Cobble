"""Demo data for the preview: realistic todos, some with a due date.

`python -m app.seed` adds them from the command line; starting the application with
TODO_SEED=1 does the same. A store that already holds todos is left alone.
"""

from datetime import date, timedelta

from app import db

# (title, done, days from today until it is due; None = no due date)
DEMO_TODOS: list[tuple[str, bool, int | None]] = [
    ("Buy oat milk and bananas", True, None),
    ("Pick up the dry cleaning before 6 pm", True, -1),
    ("Send the invoice to the print shop", True, -3),
    ("Call the dentist to book a check-up", False, 2),
    ("Water the plants on the balcony", False, 0),
    ("Plan the weekend hike with Sam", False, 4),
    ("Renew the bike insurance", False, 14),
    ("Book train tickets for Mom's birthday", False, 21),
]


def seed() -> int:
    """Insert the demo todos into an empty store and return how many were added."""
    if db.list_todos():
        return 0
    today = date.today()
    for title, done, days in DEMO_TODOS:
        due = None if days is None else today + timedelta(days=days)
        todo = db.create_todo(title, due)
        if done:
            db.set_done(todo.id, True)
    return len(DEMO_TODOS)


if __name__ == "__main__":
    print(f"{seed()} demo todos added")
