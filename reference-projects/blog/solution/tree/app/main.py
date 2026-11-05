"""Personal blog: reference solution (posts, drafts, tags, comments)."""

import json
import os
import re
import sqlite3
import unicodedata
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel, Field, StringConstraints

app = FastAPI(title="Blog")

SCHEMA = """
CREATE TABLE IF NOT EXISTS posts (
    id INTEGER PRIMARY KEY AUTOINCREMENT, slug TEXT UNIQUE NOT NULL, title TEXT NOT NULL,
    body TEXT NOT NULL, tags TEXT NOT NULL, published INTEGER NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS comments (
    id INTEGER PRIMARY KEY AUTOINCREMENT, post_id INTEGER NOT NULL, author TEXT NOT NULL,
    body TEXT NOT NULL, created_at TEXT NOT NULL);
"""

Tag = Annotated[str, StringConstraints(pattern=r"^[a-z0-9]+$", max_length=30)]
Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class PostIn(BaseModel):
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
    body: Text
    tags: list[Tag] = Field(default_factory=list, max_length=5)
    published: bool = False


class PostPatch(BaseModel):
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)] | None = None
    body: Text | None = None
    tags: list[Tag] | None = Field(default=None, max_length=5)
    published: bool | None = None


class CommentIn(BaseModel):
    author: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)]
    body: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]


def connect() -> sqlite3.Connection:
    folder = Path(os.environ.get("COBBLE_DATA_DIR", "data"))
    folder.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(folder / "blog.db")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def slugify(title: str) -> str:
    plain = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", plain.lower()).strip("-") or "post"


def view(conn: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
    count = conn.execute("SELECT COUNT(*) FROM comments WHERE post_id = ?", (row["id"],)).fetchone()[0]
    return {
        "slug": row["slug"],
        "title": row["title"],
        "body": row["body"],
        "tags": json.loads(row["tags"]),
        "published": bool(row["published"]),
        "created_at": row["created_at"],
        "comment_count": count,
    }


def find(conn: sqlite3.Connection, slug: str, *, drafts: bool = False) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM posts WHERE slug = ?", (slug,)).fetchone()
    if row is None or (not row["published"] and not drafts):
        raise HTTPException(404, "Post not found")
    return row


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/posts", status_code=201)
def create_post(payload: PostIn) -> dict[str, Any]:
    with closing(connect()) as conn, conn:
        base = slugify(payload.title)
        slug, number = base, 1
        while conn.execute("SELECT 1 FROM posts WHERE slug = ?", (slug,)).fetchone():
            number += 1
            slug = f"{base}-{number}"
        conn.execute(
            "INSERT INTO posts (slug, title, body, tags, published, created_at) VALUES (?,?,?,?,?,?)",
            (slug, payload.title, payload.body, json.dumps(payload.tags), int(payload.published),
             datetime.now(UTC).isoformat()),
        )
        return view(conn, find(conn, slug, drafts=True))


@app.get("/api/posts")
def list_posts(tag: str | None = None) -> list[dict[str, Any]]:
    with closing(connect()) as conn:
        rows = conn.execute("SELECT * FROM posts WHERE published = 1 ORDER BY id DESC").fetchall()
        posts = [view(conn, row) for row in rows]
    return [p for p in posts if tag is None or tag in p["tags"]]


@app.get("/api/drafts")
def list_drafts() -> list[dict[str, Any]]:
    with closing(connect()) as conn:
        rows = conn.execute("SELECT * FROM posts WHERE published = 0 ORDER BY id DESC").fetchall()
        return [view(conn, row) for row in rows]


@app.get("/api/posts/{slug}")
def read_post(slug: str) -> dict[str, Any]:
    with closing(connect()) as conn:
        return view(conn, find(conn, slug))


@app.patch("/api/posts/{slug}")
def update_post(slug: str, payload: PostPatch) -> dict[str, Any]:
    with closing(connect()) as conn, conn:
        row = find(conn, slug, drafts=True)
        changes = payload.model_dump(exclude_none=True)
        if "tags" in changes:
            changes["tags"] = json.dumps(changes["tags"])
        if "published" in changes:
            changes["published"] = int(changes["published"])
        for column, value in changes.items():
            conn.execute(f"UPDATE posts SET {column} = ? WHERE id = ?", (value, row["id"]))  # noqa: S608
        return view(conn, find(conn, slug, drafts=True))


@app.delete("/api/posts/{slug}", status_code=204)
def delete_post(slug: str) -> Response:
    with closing(connect()) as conn, conn:
        row = find(conn, slug, drafts=True)
        conn.execute("DELETE FROM comments WHERE post_id = ?", (row["id"],))
        conn.execute("DELETE FROM posts WHERE id = ?", (row["id"],))
    return Response(status_code=204)


@app.post("/api/posts/{slug}/comments", status_code=201)
def add_comment(slug: str, payload: CommentIn) -> dict[str, Any]:
    with closing(connect()) as conn, conn:
        row = find(conn, slug)
        created = datetime.now(UTC).isoformat()
        conn.execute(
            "INSERT INTO comments (post_id, author, body, created_at) VALUES (?,?,?,?)",
            (row["id"], payload.author, payload.body, created),
        )
        return {"author": payload.author, "body": payload.body, "created_at": created}


@app.get("/api/posts/{slug}/comments")
def list_comments(slug: str) -> list[dict[str, Any]]:
    with closing(connect()) as conn:
        row = find(conn, slug)
        rows = conn.execute("SELECT * FROM comments WHERE post_id = ? ORDER BY id", (row["id"],))
        return [{"author": r["author"], "body": r["body"], "created_at": r["created_at"]} for r in rows]
