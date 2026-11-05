"""Hidden acceptance tests: chat bot. They only use the public HTTP API of the spec."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


def say(client: TestClient, text: str, user: str = "ana") -> str:
    response = client.post("/api/messages", json={"user": user, "text": text})
    assert response.status_code == 200, response.text
    return response.json()["reply"]


def test_health(client: TestClient) -> None:
    assert client.get("/api/health").status_code == 200


def test_greeting(client: TestClient) -> None:
    assert say(client, "hello there") == "Hello ana!"
    assert say(client, "Bonjour tout le monde", user="luc") == "Hello luc!"
    assert say(client, "HI") == "Hello ana!"


def test_greeting_is_a_whole_word(client: TestClient) -> None:
    assert say(client, "this is nothing") == "Sorry, I did not understand. Try /help."
    assert say(client, "which one") == "Sorry, I did not understand. Try /help."


def test_unknown_text(client: TestClient) -> None:
    assert say(client, "qwerty") == "Sorry, I did not understand. Try /help."


def test_help_lists_the_commands(client: TestClient) -> None:
    reply = say(client, "/help")
    for command in ("/help", "/echo", "/calc", "/count"):
        assert command in reply


def test_echo(client: TestClient) -> None:
    assert say(client, "/echo Hello,  World!") == "Hello,  World!"
    assert say(client, "/ECHO shout") == "shout"
    assert say(client, "/echo") == "Usage: /echo <text>"


def test_unknown_command(client: TestClient) -> None:
    assert say(client, "/dance now") == "Unknown command: /dance. Try /help."


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("1 + 2", "3"),
        ("2 + 3 * 4", "14"),
        ("(2 + 3) * 4", "20"),
        ("10 / 4", "2.5"),
        ("1 / 3", "0.333333"),
        ("-5 + 2", "-3"),
        ("2 * -3", "-6"),
        ("0.1 + 0.2", "0.3"),
        ("100 - 1 - 1", "98"),
        ("8 / 2 / 2", "2"),
        ("((7))", "7"),
        ("3 - -3", "6"),
    ],
)
def test_calc(client: TestClient, expression: str, expected: str) -> None:
    assert say(client, f"/calc {expression}") == expected


@pytest.mark.parametrize(
    "expression", ["", "1 +", "abc", "2 ** 3", "(1 + 2", "1 2", "__import__('os')", "1 + 2)"]
)
def test_calc_refuses_what_it_cannot_read(client: TestClient, expression: str) -> None:
    assert say(client, f"/calc {expression}".rstrip()) == "Error: invalid expression"


def test_calc_division_by_zero(client: TestClient) -> None:
    assert say(client, "/calc 5 / 0") == "Error: division by zero"
    assert say(client, "/calc 1 / (2 - 2)") == "Error: division by zero"


def test_count_is_per_user(client: TestClient) -> None:
    assert say(client, "/count") == "You have sent 1 message."
    say(client, "hello")
    assert say(client, "/count") == "You have sent 3 messages."
    assert say(client, "/count", user="luc") == "You have sent 1 message."


def test_rules_answer_by_keyword(client: TestClient) -> None:
    created = client.post("/api/rules", json={"keyword": "price", "reply": "It is free."})
    assert created.status_code == 201
    assert created.json()["keyword"] == "price" and created.json()["reply"] == "It is free."
    assert say(client, "What is the PRICE today?") == "It is free."
    assert say(client, "pricey") == "Sorry, I did not understand. Try /help."


def test_the_first_rule_wins_and_rules_beat_the_greeting(client: TestClient) -> None:
    client.post("/api/rules", json={"keyword": "open", "reply": "We open at 9."})
    client.post("/api/rules", json={"keyword": "hours", "reply": "Nine to five."})
    assert say(client, "opening hours? open or not") == "We open at 9."
    assert say(client, "what are your hours") == "Nine to five."
    client.post("/api/rules", json={"keyword": "hello", "reply": "Custom hello."})
    assert say(client, "hello") == "Custom hello."


def test_commands_ignore_the_rules(client: TestClient) -> None:
    client.post("/api/rules", json={"keyword": "echo", "reply": "rule!"})
    assert say(client, "/echo echo") == "echo"


def test_rule_management(client: TestClient) -> None:
    first = client.post("/api/rules", json={"keyword": "Shipping", "reply": "2 days."}).json()
    assert client.post("/api/rules", json={"keyword": "shipping", "reply": "x"}).status_code == 409
    assert client.post("/api/rules", json={"keyword": "", "reply": "x"}).status_code == 422
    assert client.post("/api/rules", json={"keyword": "k", "reply": ""}).status_code == 422
    assert client.post("/api/rules", json={"keyword": "k" * 31, "reply": "x"}).status_code == 422
    assert [r["keyword"] for r in client.get("/api/rules").json()] == ["Shipping"]
    assert client.delete(f"/api/rules/{first['id']}").status_code == 204
    assert client.delete(f"/api/rules/{first['id']}").status_code == 404
    assert client.get("/api/rules").json() == []
    assert say(client, "shipping") == "Sorry, I did not understand. Try /help."


def test_message_validation(client: TestClient) -> None:
    def post(**fields) -> int:  # type: ignore[no-untyped-def]
        return client.post("/api/messages", json=fields).status_code

    assert post(user="ana", text="") == 422
    assert post(user="", text="hi") == 422
    assert post(user="ana") == 422
    assert post(text="hi") == 422
    assert post(user="u" * 31, text="hi") == 422
    assert post(user="ana", text="x" * 501) == 422
    assert post(user="ana", text="x" * 500) == 200


def test_history(client: TestClient) -> None:
    say(client, "hello", user="ana")
    say(client, "/echo yes", user="luc")
    say(client, "/calc 1+1", user="ana")
    everyone = client.get("/api/history").json()
    assert [(m["user"], m["text"], m["reply"]) for m in everyone] == [
        ("ana", "hello", "Hello ana!"),
        ("luc", "/echo yes", "yes"),
        ("ana", "/calc 1+1", "2"),
    ]
    assert everyone[0]["timestamp"].endswith("Z")
    only_ana = client.get("/api/history?user=ana").json()
    assert [m["text"] for m in only_ana] == ["hello", "/calc 1+1"]
    assert client.get("/api/history?user=nobody").json() == []


def test_history_limit_keeps_the_latest_in_order(client: TestClient) -> None:
    for index in range(5):
        say(client, f"/echo m{index}")
    latest = client.get("/api/history?limit=2").json()
    assert [m["text"] for m in latest] == ["/echo m3", "/echo m4"]
    assert client.get("/api/history?limit=0").status_code == 422
    assert client.get("/api/history?limit=201").status_code == 422


def test_data_survives_a_restart(launcher) -> None:  # type: ignore[no-untyped-def]
    first = launcher.start()
    first.post("/api/rules", json={"keyword": "wifi", "reply": "Password: none."})
    say(first, "hello")
    launcher.stop()
    second = launcher.start()
    assert say(second, "wifi?") == "Password: none."
    assert say(second, "/count") == "You have sent 3 messages."
