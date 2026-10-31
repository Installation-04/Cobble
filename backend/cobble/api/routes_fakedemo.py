"""The demo pages of the fake pack (`COBBLE_PACK_MODE=fake` only; never mounted otherwise).

In the real pack the preview-service serves `/demo/<project>/<milestone>/`. In fake mode the API
does, with a small static page of realistic to-do items, so the browser tests have something to
look at. Like the real route it is public (the project id is the secret) and sandboxed.
"""

from __future__ import annotations

import html
import uuid

from fastapi import APIRouter
from fastapi.responses import HTMLResponse
from sqlalchemy import select

from cobble.db import Task
from cobble.scheduler import demo, rules

from .deps import Db
from .errors import ApiError

router = APIRouter()

ITEMS = [
    ("Book the dentist appointment", "Today", False),
    ("Buy groceries for the weekend dinner", "Tomorrow", False),
    ("Send the invoice to Martin & Co", "Friday", True),
    ("Renew the car insurance", "Next week", False),
    ("Plan the team offsite agenda", "Next week", False),
    ("Call the plumber about the kitchen tap", "Done", True),
]
SANDBOX = "sandbox allow-scripts allow-forms allow-popups allow-modals"


def render(title: str, ref: str, revision: int, count: int, comments: list[str]) -> str:
    rows = "".join(
        f'<li data-testid="todo" class="{"done" if done else ""}">'
        f"<input type='checkbox' disabled {'checked' if done else ''}> "
        f"<span>{html.escape(text)}</span> <small>{html.escape(due)}</small></li>"
        for text, due, done in ITEMS[:count]
    )
    notes = "".join(f"<li>{html.escape(c)}</li>" for c in comments)
    applied = f'<h2>Applied comments</h2><ul id="comments">{notes}</ul>' if notes else ""
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{html.escape(title)} - {html.escape(ref)}</title>"
        "<style>body{font-family:system-ui,sans-serif;max-width:40rem;margin:2rem auto;"
        "padding:0 1rem}"
        "li{list-style:none;padding:.4rem 0;border-bottom:1px solid #8884}"
        ".done span{text-decoration:line-through;opacity:.7}small{opacity:.7;margin-left:.5rem}"
        "</style></head><body>"
        f"<h1>{html.escape(title)}</h1>"
        '<p data-testid="demo-meta">'
        f"Fake demo of milestone {html.escape(ref)}, build {revision + 1}</p>"
        f'<ul id="todos">{rows}</ul>{applied}</body></html>'
    )


@router.get("/demo/{project_id}/{milestone}/", response_class=HTMLResponse)
@router.get("/demo/{project_id}/{milestone}", response_class=HTMLResponse)
def fake_demo(project_id: str, milestone: str, db: Db) -> HTMLResponse:
    try:
        pid = uuid.UUID(project_id)
    except ValueError:
        raise ApiError(404, "not_found") from None
    try:
        found = demo.get_milestone(db, pid, milestone)
    except demo.DemoError:
        raise ApiError(404, "not_found") from None
    if found.status == demo.PENDING:
        raise ApiError(404, "not_found")
    order = [m.ref for m in demo.milestones_of(db, pid)]
    count = min(len(ITEMS), 4 + order.index(milestone) + 1)
    tasks = db.scalars(
        select(Task).where(
            Task.project_id == pid,
            Task.milestone == milestone,
            Task.kind == "comment",
            Task.state == rules.MERGED,
        )
    )
    comments = [t.acceptance[0] for t in sorted(tasks, key=lambda t: rules.ref_key(t.ref))]
    body = render(found.title, found.ref, found.revision, count, comments)
    return HTMLResponse(
        body, headers={"Content-Security-Policy": SANDBOX, "Cache-Control": "no-store"}
    )
