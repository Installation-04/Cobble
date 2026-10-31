"""Demo data for the preview of milestone M1 (the task API).

`python -m app.seed` adds them from the command line; starting the application with
TODO_SEED=1 does the same. A store that already holds todos is left alone.
"""

from app import db

DEMO_TODOS = [
    ("Buy oat milk and bananas", True),
    ("Call the dentist to book a check-up", False),
    ("Reply to Marie about Saturday dinner", True),
    ("Renew the library card", False),
    ("Water the plants on the balcony", False),
    ("Pay the electricity bill", True),
    ("Back up the photos from the trip", False),
    ("Book train tickets for Mom's birthday", False),
]


def seed() -> int:
    """Insert the demo todos into an empty store and return how many were added."""
    if db.list_todos():
        return 0
    for title, done in DEMO_TODOS:
        todo = db.create_todo(title)
        if done:
            db.set_done(todo.id, True)
    return len(DEMO_TODOS)


if __name__ == "__main__":
    print(f"{seed()} demo todos added")
