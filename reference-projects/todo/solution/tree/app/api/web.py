"""Serve the web page: the built frontend when it exists, a small notice otherwise."""

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse, HTMLResponse, Response

router = APIRouter()

BUILT_PAGE = Path(__file__).resolve().parents[2] / "frontend" / "dist" / "index.html"

NOTICE_PAGE = """<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>To-do list</title>
  </head>
  <body>
    <h1>To-do list</h1>
    <p>The page is not built yet: run "pnpm build" in the frontend folder.</p>
  </body>
</html>
"""


@router.get("/", include_in_schema=False)
def index() -> Response:
    if BUILT_PAGE.is_file():
        return FileResponse(BUILT_PAGE)
    return HTMLResponse(NOTICE_PAGE)
