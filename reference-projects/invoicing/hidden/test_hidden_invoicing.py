"""Hidden acceptance tests: invoicing API. They only use the public HTTP API of the spec."""

from __future__ import annotations

from fastapi.testclient import TestClient


def customer(client: TestClient, name: str = "Acme Inc", email: str = "bill@acme.test") -> dict:
    response = client.post("/api/customers", json={"name": name, "email": email})
    assert response.status_code == 201, response.text
    return response.json()


def invoice(client: TestClient, customer_id: int, lines: list | None = None, **extra) -> dict:  # type: ignore[no-untyped-def]
    body = {
        "customer_id": customer_id,
        "lines": lines or [{"description": "Work", "quantity": 1, "unit_price": "10.00"}],
        **extra,
    }
    response = client.post("/api/invoices", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def line(quantity: int, unit_price: str, description: str = "Item") -> dict:
    return {"description": description, "quantity": quantity, "unit_price": unit_price}


def test_health(client: TestClient) -> None:
    assert client.get("/api/health").status_code == 200


def test_customers(client: TestClient) -> None:
    created = customer(client, "Ana", "ana@example.test")
    assert created["name"] == "Ana" and created["email"] == "ana@example.test"
    customer(client, "Bob", "bob@example.test")
    assert [c["name"] for c in client.get("/api/customers").json()] == ["Ana", "Bob"]
    assert client.get(f"/api/customers/{created['id']}").json()["email"] == "ana@example.test"
    assert client.get("/api/customers/999").status_code == 404


def test_customer_validation(client: TestClient) -> None:
    assert client.post("/api/customers", json={"name": "", "email": "a@b.co"}).status_code == 422
    assert client.post("/api/customers", json={"name": "A", "email": "nope"}).status_code == 422
    assert client.post("/api/customers", json={"name": "A"}).status_code == 422


def test_a_new_invoice_is_a_draft_with_money_as_two_decimal_strings(client: TestClient) -> None:
    cid = customer(client)["id"]
    created = invoice(client, cid, [line(3, "19.99", "Chairs"), line(1, "0.05", "Tag")])
    assert created["status"] == "draft"
    assert created["customer_id"] == cid
    assert [ln["amount"] for ln in created["lines"]] == ["59.97", "0.05"]
    assert created["lines"][0]["unit_price"] == "19.99"
    assert created["subtotal"] == "60.02"
    assert created["tax"] == "0.00"
    assert created["total"] == "60.02"


def test_tax_is_computed_on_the_subtotal(client: TestClient) -> None:
    cid = customer(client)["id"]
    created = invoice(client, cid, [line(3, "19.99"), line(1, "0.05")], tax_rate=5.5)
    assert created["tax_rate"] == 5.5
    assert created["subtotal"] == "60.02"
    assert created["tax"] == "3.30"  # 3.3011 rounded
    assert created["total"] == "63.32"


def test_tax_rounds_half_up(client: TestClient) -> None:
    cid = customer(client)["id"]
    created = invoice(client, cid, [line(1, "0.10")], tax_rate=5)  # 0.005 -> 0.01
    assert created["tax"] == "0.01"
    assert created["total"] == "0.11"
    other = invoice(client, cid, [line(1, "2.50")], tax_rate=15)  # 0.375 -> 0.38
    assert other["tax"] == "0.38"
    assert other["total"] == "2.88"
    classic = invoice(client, cid, [line(1, "53.50")], tax_rate=5)  # 2.675 -> 2.68
    assert classic["tax"] == "2.68"
    assert classic["total"] == "56.18"


def test_no_floating_point_drift(client: TestClient) -> None:
    cid = customer(client)["id"]
    lines = [line(1, "0.10"), line(1, "0.20"), line(1, "0.30")]
    created = invoice(client, cid, lines)
    assert created["subtotal"] == "0.60"
    big = invoice(client, cid, [line(7, "1234567.89")], tax_rate=20)
    assert big["subtotal"] == "8641975.23"
    assert big["tax"] == "1728395.05"
    assert big["total"] == "10370370.28"


def test_invoice_validation(client: TestClient) -> None:
    cid = customer(client)["id"]

    def create(**fields) -> int:  # type: ignore[no-untyped-def]
        return client.post("/api/invoices", json={"customer_id": cid, **fields}).status_code

    assert create(lines=[]) == 422
    assert create() == 422
    assert create(lines=[line(0, "1.00")]) == 422
    assert create(lines=[line(-2, "1.00")]) == 422
    assert create(lines=[line(1, "1.005")]) == 422
    assert create(lines=[line(1, "-1.00")]) == 422
    assert create(lines=[line(1, "abc")]) == 422
    assert create(lines=[line(1, "1.00")], tax_rate=-1) == 422
    assert create(lines=[line(1, "1.00")], tax_rate=100.5) == 422
    assert create(lines=[line(1, "1.00")], tax_rate=100) == 201


def test_unknown_customer_is_404(client: TestClient) -> None:
    body = {"customer_id": 42, "lines": [line(1, "1.00")]}
    assert client.post("/api/invoices", json=body).status_code == 404


def test_numbers_are_sequential_and_never_reused(client: TestClient) -> None:
    cid = customer(client)["id"]
    first, second = invoice(client, cid), invoice(client, cid)
    assert (first["number"], second["number"]) == ("INV-0001", "INV-0002")
    assert client.delete(f"/api/invoices/{second['id']}").status_code == 204
    assert invoice(client, cid)["number"] == "INV-0003"


def test_status_workflow(client: TestClient) -> None:
    cid = customer(client)["id"]
    created = invoice(client, cid)
    url = f"/api/invoices/{created['id']}"
    assert client.post(f"{url}/pay").status_code == 409  # a draft cannot be paid
    sent = client.post(f"{url}/send")
    assert sent.status_code == 200 and sent.json()["status"] == "sent"
    assert client.post(f"{url}/send").status_code == 409
    paid = client.post(f"{url}/pay")
    assert paid.status_code == 200 and paid.json()["status"] == "paid"
    assert client.post(f"{url}/pay").status_code == 409
    assert client.get(url).json()["status"] == "paid"
    assert client.post("/api/invoices/999/send").status_code == 404


def test_only_a_draft_can_be_edited_or_deleted(client: TestClient) -> None:
    cid = customer(client)["id"]
    created = invoice(client, cid, [line(1, "100.00")])
    url = f"/api/invoices/{created['id']}"
    edited = client.patch(url, json={"lines": [line(2, "100.00")], "tax_rate": 10})
    assert edited.status_code == 200
    assert (edited.json()["subtotal"], edited.json()["tax"], edited.json()["total"]) == (
        "200.00",
        "20.00",
        "220.00",
    )
    client.post(f"{url}/send")
    assert client.patch(url, json={"tax_rate": 0}).status_code == 409
    assert client.delete(url).status_code == 409
    assert client.get(url).json()["total"] == "220.00"


def test_filters_and_order(client: TestClient) -> None:
    ana, bob = customer(client, "Ana")["id"], customer(client, "Bob", "bob@x.test")["id"]
    a1, b1, a2 = invoice(client, ana), invoice(client, bob), invoice(client, ana)
    client.post(f"/api/invoices/{a1['id']}/send")
    numbers = [i["number"] for i in client.get("/api/invoices").json()]
    assert numbers == ["INV-0001", "INV-0002", "INV-0003"]
    assert [i["id"] for i in client.get(f"/api/invoices?customer_id={ana}").json()] == [
        a1["id"],
        a2["id"],
    ]
    assert [i["id"] for i in client.get("/api/invoices?status=sent").json()] == [a1["id"]]
    assert [i["id"] for i in client.get("/api/invoices?status=draft").json()] == [b1["id"], a2["id"]]


def test_a_customer_with_invoices_cannot_be_deleted(client: TestClient) -> None:
    cid = customer(client)["id"]
    created = invoice(client, cid)
    assert client.delete(f"/api/customers/{cid}").status_code == 409
    client.delete(f"/api/invoices/{created['id']}")
    assert client.delete(f"/api/customers/{cid}").status_code == 204
    assert client.get(f"/api/customers/{cid}").status_code == 404


def test_summary(client: TestClient) -> None:
    cid = customer(client)["id"]
    a = invoice(client, cid, [line(1, "100.00")], tax_rate=10)  # 110.00
    b = invoice(client, cid, [line(2, "25.50")])  # 51.00
    invoice(client, cid, [line(1, "5.00")])  # 5.00, stays a draft
    client.post(f"/api/invoices/{a['id']}/send")
    client.post(f"/api/invoices/{b['id']}/send")
    client.post(f"/api/invoices/{b['id']}/pay")
    summary = client.get("/api/reports/summary").json()
    assert summary["draft"] == {"count": 1, "total": "5.00"}
    assert summary["sent"] == {"count": 1, "total": "110.00"}
    assert summary["paid"] == {"count": 1, "total": "51.00"}
    assert summary["outstanding"] == "110.00"


def test_data_survives_a_restart(launcher) -> None:  # type: ignore[no-untyped-def]
    first = launcher.start()
    cid = customer(first)["id"]
    created = invoice(first, cid, [line(2, "9.99")], tax_rate=20)
    first.post(f"/api/invoices/{created['id']}/send")
    launcher.stop()
    second = launcher.start()
    again = second.get(f"/api/invoices/{created['id']}").json()
    assert (again["number"], again["status"], again["total"]) == ("INV-0001", "sent", "23.98")
    assert invoice(second, cid)["number"] == "INV-0002"
