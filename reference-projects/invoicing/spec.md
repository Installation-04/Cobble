# Invoicing API

A small invoicing service for one freelancer. Customers, invoices with lines and tax, and a status that follows the invoice from draft to paid. No accounts and no login.

## Features
- Customers: name (1 to 100 characters) and email (must look like an email address). List them, read one, delete one. A customer who has invoices cannot be deleted.
- Invoices: for a customer, a tax rate and at least one line. A line has a description (1 to 100 characters), a quantity (integer, at least 1) and a unit price.
- **Money is exact.** Prices are sent and returned as strings with exactly two decimals (`"19.99"`); a price with more than two decimals, a negative price or a non-number is refused. Never use binary floating point to compute amounts.
- The amount of a line is quantity times unit price. The subtotal is the sum of the line amounts. The tax is the subtotal times the tax rate (a percentage between 0 and 100, 0 by default, sent as a JSON number such as `5.5`), **rounded half up to two decimals** (0.005 becomes 0.01). The total is the subtotal plus the tax. All of them are returned as two-decimal strings.
- Each invoice has a number `INV-0001`, `INV-0002`... assigned in order of creation. A number is never reused, even if the invoice with the highest number is deleted.
- Status: a new invoice is a `draft`. `send` moves a draft to `sent`; `pay` moves a sent invoice to `paid`. Any other move is refused with 409.
- Only a draft can be edited (tax rate and lines; the totals are recomputed) or deleted. Anything else is refused with 409.
- List the invoices in number order, optionally filtered with `?status=` and `?customer_id=`.
- A summary report: for each of `draft`, `sent`, `paid`, the number of invoices and the sum of their totals; plus `outstanding`, the sum of the totals still to be paid (the `sent` ones).

## Screens
- A page to create customers and invoices, see the invoice list with its status, and send or mark paid.

## Data model
- Customer: id, name, email.
- Invoice: id, number, customer_id, status, tax_rate, lines (description, quantity, unit_price, amount), subtotal, tax, total.

## Constraints
- FastAPI backend, data kept on disk (it survives a restart).
- Usable on a phone screen.

## Out of scope
- Currencies other than a single one, PDF, email sending, several tax rates per invoice, authentication.

## Acceptance criteria
- `GET /api/health` answers 200.
- `POST /api/customers`, `GET /api/customers`, `GET /api/customers/{id}`, `DELETE /api/customers/{id}` (201, 200, 200 or 404, 204 or 409).
- `POST /api/invoices` (201; 404 for an unknown customer; 422 for invalid fields), `GET /api/invoices`, `GET /api/invoices/{id}`, `PATCH /api/invoices/{id}`, `DELETE /api/invoices/{id}`.
- `POST /api/invoices/{id}/send` and `POST /api/invoices/{id}/pay` answer 200 with the invoice, 409 for a forbidden move, 404 if unknown.
- `GET /api/reports/summary` answers `{"draft": {"count", "total"}, "sent": {...}, "paid": {...}, "outstanding": "..."}`.
