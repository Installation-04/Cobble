# Simple to-do list

A personal to-do list used from a phone. One user, no account.

## Features
- Add a task with a title.
- List all tasks, oldest first.
- Tick a task as done, or untick it.
- Delete a task.

## Screens
- A single page: a form to add a task, then the list.
- Each task has a checkbox and a delete button.

## Data model
- Todo: id (integer), title (text, 1 to 200 characters), done (boolean, false by default).

## Constraints
- FastAPI backend with a simple web page; data survives a restart.
- Usable on a phone screen (375 px wide).

## Out of scope
- Accounts, sharing, due dates, categories, notifications.

## Acceptance (hidden tests)
- `GET /api/health` returns 200.
- `POST /api/todos` with a title returns 201 and the todo; an empty title returns 422.
- `GET /api/todos` lists todos oldest first.
- `PATCH /api/todos/{id}` with `done` updates it; `DELETE /api/todos/{id}` returns 204; an unknown id returns 404.
- `GET /` serves the page.
