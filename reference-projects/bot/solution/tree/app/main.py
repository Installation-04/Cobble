"""Chat bot API: reference solution (commands, keyword rules, history)."""

import os
import re
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from decimal import Decimal, DivisionByZero, InvalidOperation
from pathlib import Path
from typing import Annotated, Any

from fastapi import FastAPI, HTTPException, Query, Response
from pydantic import BaseModel, StringConstraints

app = FastAPI(title="Bot")

SCHEMA = """
CREATE TABLE IF NOT EXISTS history (
    id INTEGER PRIMARY KEY AUTOINCREMENT, user TEXT NOT NULL, text TEXT NOT NULL,
    reply TEXT NOT NULL, timestamp TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT, keyword TEXT NOT NULL, reply TEXT NOT NULL);
"""
COMMANDS = ("/help", "/echo", "/calc", "/count")
GREETING = re.compile(r"\b(hello|hi|bonjour|salut)\b", re.IGNORECASE)
FALLBACK = "Sorry, I did not understand. Try /help."


class MessageIn(BaseModel):
    user: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=30)]
    text: Annotated[str, StringConstraints(min_length=1, max_length=500)]


class RuleIn(BaseModel):
    keyword: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=30)]
    reply: Annotated[str, StringConstraints(min_length=1, max_length=200)]


def connect() -> sqlite3.Connection:
    folder = Path(os.environ.get("COBBLE_DATA_DIR", "data"))
    folder.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(folder / "bot.db")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


class CalcError(Exception):
    pass


def calculate(expression: str) -> Decimal:
    """+ - * / on decimal numbers with parentheses and unary minus; never `eval`."""
    tokens = re.findall(r"\d+(?:\.\d+)?|[-+*/()]|\S", expression)
    position = 0

    def peek() -> str | None:
        return tokens[position] if position < len(tokens) else None

    def take() -> str:
        nonlocal position
        position += 1
        return tokens[position - 1]

    def atom() -> Decimal:
        token = peek()
        if token is None:
            raise CalcError
        if token == "-":
            take()
            return -atom()
        if token == "(":
            take()
            value = expr()
            if peek() != ")":
                raise CalcError
            take()
            return value
        if re.fullmatch(r"\d+(?:\.\d+)?", token):
            return Decimal(take())
        raise CalcError

    def term() -> Decimal:
        value = atom()
        while peek() in ("*", "/"):
            op = take()
            right = atom()
            value = value * right if op == "*" else value / right
        return value

    def expr() -> Decimal:
        value = term()
        while peek() in ("+", "-"):
            op = take()
            right = term()
            value = value + right if op == "+" else value - right
        return value

    result = expr()
    if peek() is not None:
        raise CalcError
    return result


def number(value: Decimal) -> str:
    text = f"{value.quantize(Decimal('0.000001')):f}".rstrip("0").rstrip(".")
    return "0" if text in ("", "-0") else text


def command_reply(conn: sqlite3.Connection, user: str, text: str) -> str:
    name, _, rest = text.partition(" ")
    name = name.lower()
    if name == "/help":
        return "Commands: " + ", ".join(COMMANDS)
    if name == "/echo":
        return rest if rest.strip() else "Usage: /echo <text>"
    if name == "/calc":
        try:
            return number(calculate(rest))
        except (CalcError, InvalidOperation):
            return "Error: invalid expression"
        except (DivisionByZero, ZeroDivisionError):
            return "Error: division by zero"
    if name == "/count":
        total = conn.execute("SELECT COUNT(*) FROM history WHERE user = ?", (user,)).fetchone()[0] + 1
        return f"You have sent {total} message{'' if total == 1 else 's'}."
    return f"Unknown command: {name}. Try /help."


def plain_reply(conn: sqlite3.Connection, user: str, text: str) -> str:
    for rule in conn.execute("SELECT * FROM rules ORDER BY id"):
        if re.search(rf"\b{re.escape(rule['keyword'])}\b", text, re.IGNORECASE):
            return str(rule["reply"])
    if GREETING.search(text):
        return f"Hello {user}!"
    return FALLBACK


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/messages")
def send_message(payload: MessageIn) -> dict[str, Any]:
    with closing(connect()) as conn, conn:
        if payload.text.startswith("/"):
            reply = command_reply(conn, payload.user, payload.text)
        else:
            reply = plain_reply(conn, payload.user, payload.text)
        conn.execute(
            "INSERT INTO history (user, text, reply, timestamp) VALUES (?,?,?,?)",
            (payload.user, payload.text, reply, datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")),
        )
    return {"reply": reply}


@app.get("/api/history")
def history(user: str | None = None, limit: int = Query(50, ge=1, le=200)) -> list[dict[str, Any]]:
    with closing(connect()) as conn:
        sql, args = "SELECT * FROM history", []
        if user is not None:
            sql, args = sql + " WHERE user = ?", [user]
        rows = conn.execute(sql + " ORDER BY id DESC LIMIT ?", [*args, limit]).fetchall()
    return [
        {"user": r["user"], "text": r["text"], "reply": r["reply"], "timestamp": r["timestamp"]}
        for r in reversed(rows)
    ]


@app.post("/api/rules", status_code=201)
def add_rule(payload: RuleIn) -> dict[str, Any]:
    with closing(connect()) as conn, conn:
        if conn.execute("SELECT 1 FROM rules WHERE lower(keyword) = ?", (payload.keyword.lower(),)).fetchone():
            raise HTTPException(409, "A rule already uses this keyword")
        cursor = conn.execute("INSERT INTO rules (keyword, reply) VALUES (?, ?)", (payload.keyword, payload.reply))
        return {"id": cursor.lastrowid, "keyword": payload.keyword, "reply": payload.reply}


@app.get("/api/rules")
def list_rules() -> list[dict[str, Any]]:
    with closing(connect()) as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM rules ORDER BY id")]


@app.delete("/api/rules/{rule_id}", status_code=204)
def delete_rule(rule_id: int) -> Response:
    with closing(connect()) as conn, conn:
        if conn.execute("DELETE FROM rules WHERE id = ?", (rule_id,)).rowcount == 0:
            raise HTTPException(404, "Rule not found")
    return Response(status_code=204)
