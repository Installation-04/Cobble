"""Metrics dashboard API: reference solution (events in, summaries and series out)."""

import os
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, StringConstraints, field_validator

app = FastAPI(title="Dashboard")

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, value REAL NOT NULL,
    source TEXT NOT NULL, ts TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS events_name ON events (name, ts);
"""
Name = Annotated[str, StringConstraints(pattern=r"^[a-z0-9_.]+$", min_length=1, max_length=50)]


def parse_ts(text: str) -> datetime:
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("not an ISO 8601 date") from None
    return (moment if moment.tzinfo else moment.replace(tzinfo=UTC)).astimezone(UTC)


def fmt(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class EventIn(BaseModel):
    name: Name
    value: float
    source: Annotated[str, StringConstraints(min_length=1, max_length=50)] = "default"
    timestamp: str | None = None

    @field_validator("timestamp")
    @classmethod
    def _timestamp(cls, value: str | None) -> str | None:
        if value is not None:
            parse_ts(value)
        return value


def connect() -> sqlite3.Connection:
    folder = Path(os.environ.get("COBBLE_DATA_DIR", "data"))
    folder.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(folder / "dashboard.db")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def bound(text: str | None) -> str | None:
    if text is None:
        return None
    try:
        return fmt(parse_ts(text))
    except ValueError:
        raise HTTPException(422, "Invalid date") from None


def rows_of(
    conn: sqlite3.Connection, name: str, start: str | None, end: str | None
) -> list[sqlite3.Row]:
    if not conn.execute("SELECT 1 FROM events WHERE name = ? LIMIT 1", (name,)).fetchone():
        raise HTTPException(404, "Unknown metric")
    sql, args = "SELECT * FROM events WHERE name = ?", [name]
    if bound(start):
        sql, args = sql + " AND ts >= ?", [*args, bound(start)]
    if bound(end):
        sql, args = sql + " AND ts < ?", [*args, bound(end)]
    return conn.execute(sql + " ORDER BY ts, id", args).fetchall()


def stats(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"count": 0, "sum": 0, "min": None, "max": None, "avg": None}
    return {
        "count": len(values),
        "sum": round(sum(values), 2),
        "min": min(values),
        "max": max(values),
        "avg": round(sum(values) / len(values), 2),
    }


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/events", status_code=201)
def add_event(payload: EventIn) -> dict[str, Any]:
    moment = parse_ts(payload.timestamp) if payload.timestamp else datetime.now(UTC)
    with closing(connect()) as conn, conn:
        cursor = conn.execute(
            "INSERT INTO events (name, value, source, ts) VALUES (?,?,?,?)",
            (payload.name, payload.value, payload.source, fmt(moment)),
        )
    return {
        "id": cursor.lastrowid,
        "name": payload.name,
        "value": payload.value,
        "source": payload.source,
        "timestamp": fmt(moment),
    }


@app.delete("/api/events")
def delete_events(name: str) -> dict[str, int]:
    with closing(connect()) as conn, conn:
        return {"deleted": conn.execute("DELETE FROM events WHERE name = ?", (name,)).rowcount}


@app.get("/api/metrics")
def list_metrics() -> list[dict[str, Any]]:
    with closing(connect()) as conn:
        rows = conn.execute(
            "SELECT name, COUNT(*) AS n FROM events GROUP BY name ORDER BY name"
        ).fetchall()
    return [{"name": r["name"], "count": r["n"]} for r in rows]


@app.get("/api/metrics/{name}/summary")
def summary(name: str, start: str | None = Query(None, alias="from"), to: str | None = None) -> dict[str, Any]:
    with closing(connect()) as conn:
        rows = rows_of(conn, name, start, to)
    return {"name": name, **stats([r["value"] for r in rows])}


@app.get("/api/metrics/{name}/series")
def series(
    name: str,
    bucket: Literal["hour", "day"] = "day",
    start: str | None = Query(None, alias="from"),
    to: str | None = None,
) -> list[dict[str, Any]]:
    with closing(connect()) as conn:
        rows = rows_of(conn, name, start, to)
    width = 13 if bucket == "hour" else 10  # characters of the ISO timestamp that name the bucket
    groups: dict[str, list[float]] = {}
    for row in rows:
        groups.setdefault(row["ts"][:width], []).append(row["value"])
    suffix = ":00:00Z" if bucket == "hour" else "T00:00:00Z"
    return [
        {"start": key + suffix, **{k: v for k, v in stats(values).items() if k in ("count", "sum", "avg")}}
        for key, values in sorted(groups.items())
    ]


@app.get("/api/metrics/{name}/top-sources")
def top_sources(name: str, limit: int = Query(3, ge=1, le=20)) -> list[dict[str, Any]]:
    with closing(connect()) as conn:
        rows = rows_of(conn, name, None, None)
    totals: dict[str, float] = {}
    for row in rows:
        totals[row["source"]] = totals.get(row["source"], 0) + row["value"]
    ranked = sorted(totals.items(), key=lambda item: (-item[1], item[0]))
    return [{"source": source, "sum": round(total, 2)} for source, total in ranked[:limit]]
