"""Invoicing API: reference solution (customers, invoices, totals, status workflow)."""

import json
import os
import sqlite3
from contextlib import closing
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from typing import Annotated, Any

from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel, Field, StringConstraints, field_validator

app = FastAPI(title="Invoicing")

SCHEMA = """
CREATE TABLE IF NOT EXISTS customers (
    id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, email TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS invoices (
    id INTEGER PRIMARY KEY AUTOINCREMENT, customer_id INTEGER NOT NULL, status TEXT NOT NULL,
    tax_rate TEXT NOT NULL, lines TEXT NOT NULL);
"""
CENT = Decimal("0.01")
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


def money(value: Decimal) -> str:
    return f"{value.quantize(CENT, rounding=ROUND_HALF_UP):.2f}"


class CustomerIn(BaseModel):
    name: Name
    email: Annotated[str, StringConstraints(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")]


class LineIn(BaseModel):
    description: Name
    quantity: int = Field(ge=1)
    unit_price: str

    @field_validator("unit_price")
    @classmethod
    def _price(cls, value: str) -> str:
        try:
            price = Decimal(value)
        except InvalidOperation:
            raise ValueError("not a number") from None
        if not price.is_finite() or price < 0 or price != price.quantize(CENT):
            raise ValueError("a price has at most 2 decimals and is not negative")
        return value


class InvoiceIn(BaseModel):
    customer_id: int
    tax_rate: Decimal = Field(default=Decimal(0), ge=0, le=100)
    lines: list[LineIn] = Field(min_length=1)


class InvoicePatch(BaseModel):
    tax_rate: Decimal | None = Field(default=None, ge=0, le=100)
    lines: list[LineIn] | None = Field(default=None, min_length=1)


def connect() -> sqlite3.Connection:
    folder = Path(os.environ.get("COBBLE_DATA_DIR", "data"))
    folder.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(folder / "invoicing.db")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def totals(rate: Decimal, lines: list[dict[str, Any]]) -> dict[str, Any]:
    subtotal = sum((Decimal(line["quantity"]) * Decimal(line["unit_price"]) for line in lines), Decimal(0))
    tax = (subtotal * rate / 100).quantize(CENT, rounding=ROUND_HALF_UP)
    return {"subtotal": money(subtotal), "tax": money(tax), "total": money(subtotal + tax)}


def invoice_view(row: sqlite3.Row) -> dict[str, Any]:
    rate = Decimal(row["tax_rate"])
    lines = [
        {**line, "unit_price": money(Decimal(line["unit_price"])),
         "amount": money(line["quantity"] * Decimal(line["unit_price"]))}
        for line in json.loads(row["lines"])
    ]
    return {
        "id": row["id"],
        "number": f"INV-{row['id']:04d}",
        "customer_id": row["customer_id"],
        "status": row["status"],
        "tax_rate": float(rate) if rate != rate.to_integral() else int(rate),
        "lines": lines,
        **totals(rate, json.loads(row["lines"])),
    }


def get_invoice(conn: sqlite3.Connection, invoice_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM invoices WHERE id = ?", (invoice_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Invoice not found")
    return row


def get_customer(conn: sqlite3.Connection, customer_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM customers WHERE id = ?", (customer_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Customer not found")
    return row


def lines_json(lines: list[LineIn]) -> str:
    return json.dumps([line.model_dump() for line in lines])


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/customers", status_code=201)
def create_customer(payload: CustomerIn) -> dict[str, Any]:
    with closing(connect()) as conn, conn:
        cursor = conn.execute(
            "INSERT INTO customers (name, email) VALUES (?, ?)", (payload.name, payload.email)
        )
        return {"id": cursor.lastrowid, "name": payload.name, "email": payload.email}


@app.get("/api/customers")
def list_customers() -> list[dict[str, Any]]:
    with closing(connect()) as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM customers ORDER BY id")]


@app.get("/api/customers/{customer_id}")
def read_customer(customer_id: int) -> dict[str, Any]:
    with closing(connect()) as conn:
        return dict(get_customer(conn, customer_id))


@app.delete("/api/customers/{customer_id}", status_code=204)
def delete_customer(customer_id: int) -> Response:
    with closing(connect()) as conn, conn:
        get_customer(conn, customer_id)
        if conn.execute("SELECT 1 FROM invoices WHERE customer_id = ?", (customer_id,)).fetchone():
            raise HTTPException(409, "The customer has invoices")
        conn.execute("DELETE FROM customers WHERE id = ?", (customer_id,))
    return Response(status_code=204)


@app.post("/api/invoices", status_code=201)
def create_invoice(payload: InvoiceIn) -> dict[str, Any]:
    with closing(connect()) as conn, conn:
        get_customer(conn, payload.customer_id)
        cursor = conn.execute(
            "INSERT INTO invoices (customer_id, status, tax_rate, lines) VALUES (?, 'draft', ?, ?)",
            (payload.customer_id, str(payload.tax_rate), lines_json(payload.lines)),
        )
        return invoice_view(get_invoice(conn, int(cursor.lastrowid or 0)))


@app.get("/api/invoices")
def list_invoices(status: str | None = None, customer_id: int | None = None) -> list[dict[str, Any]]:
    with closing(connect()) as conn:
        rows = conn.execute("SELECT * FROM invoices ORDER BY id").fetchall()
    views = [invoice_view(r) for r in rows]
    return [
        v for v in views
        if (status is None or v["status"] == status)
        and (customer_id is None or v["customer_id"] == customer_id)
    ]


@app.get("/api/invoices/{invoice_id}")
def read_invoice(invoice_id: int) -> dict[str, Any]:
    with closing(connect()) as conn:
        return invoice_view(get_invoice(conn, invoice_id))


@app.patch("/api/invoices/{invoice_id}")
def update_invoice(invoice_id: int, payload: InvoicePatch) -> dict[str, Any]:
    with closing(connect()) as conn, conn:
        row = get_invoice(conn, invoice_id)
        if row["status"] != "draft":
            raise HTTPException(409, "Only a draft can be edited")
        rate = str(payload.tax_rate) if payload.tax_rate is not None else row["tax_rate"]
        lines = lines_json(payload.lines) if payload.lines is not None else row["lines"]
        conn.execute("UPDATE invoices SET tax_rate = ?, lines = ? WHERE id = ?", (rate, lines, invoice_id))
        return invoice_view(get_invoice(conn, invoice_id))


@app.delete("/api/invoices/{invoice_id}", status_code=204)
def delete_invoice(invoice_id: int) -> Response:
    with closing(connect()) as conn, conn:
        if get_invoice(conn, invoice_id)["status"] != "draft":
            raise HTTPException(409, "Only a draft can be deleted")
        conn.execute("DELETE FROM invoices WHERE id = ?", (invoice_id,))
    return Response(status_code=204)


def move(invoice_id: int, before: str, after: str) -> dict[str, Any]:
    with closing(connect()) as conn, conn:
        if get_invoice(conn, invoice_id)["status"] != before:
            raise HTTPException(409, f"The invoice is not {before}")
        conn.execute("UPDATE invoices SET status = ? WHERE id = ?", (after, invoice_id))
        return invoice_view(get_invoice(conn, invoice_id))


@app.post("/api/invoices/{invoice_id}/send")
def send_invoice(invoice_id: int) -> dict[str, Any]:
    return move(invoice_id, "draft", "sent")


@app.post("/api/invoices/{invoice_id}/pay")
def pay_invoice(invoice_id: int) -> dict[str, Any]:
    return move(invoice_id, "sent", "paid")


@app.get("/api/reports/summary")
def summary() -> dict[str, Any]:
    result: dict[str, Any] = {}
    for status in ("draft", "sent", "paid"):
        found = list_invoices(status=status)
        result[status] = {
            "count": len(found),
            "total": money(sum((Decimal(v["total"]) for v in found), Decimal(0))),
        }
    result["outstanding"] = result["sent"]["total"]
    return result
