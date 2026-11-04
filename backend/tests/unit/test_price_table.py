"""The table of model prices: changes are noticed and warned about, free tiers are marked,
and a rate-limited model is left alone for a while (ADR 0013)."""

from __future__ import annotations

import io
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy.orm import Session, sessionmaker

from cobble.capabilities.llm import Role
from cobble.cli_models import run
from cobble.cli_modules import Terminal
from cobble.config import Settings
from cobble.db.models import ModelPrice
from cobble.router import price_table
from cobble.router.costs import CostRouter, RateLimitBackoff
from cobble.router.gateway import GatewayError
from cobble.router.prices import Listed, Prices, parse_all

from .test_cli_models import API as FakeAPI
from .test_cli_models import parse
from .test_costs_api import API, call, client_for, pid  # noqa: F401
from .test_prices import entry
from .test_role_routes import Budget, Gateway


def listed(
    name: str, prompt: str | None, completion: str | None = None, up: str | None = None
) -> Listed:
    prices = None if prompt is None else Prices(Decimal(prompt), Decimal(completion or prompt))
    return Listed(name, prices, up)


# --- reading the gateway -------------------------------------------------------------------


def test_every_model_of_the_gateway_is_listed_with_its_provider_name() -> None:
    body = {
        "data": [
            entry("a", {"input_cost_per_token": 1, "output_cost_per_token": 2}, {"model": "x/a"}),
            entry("b", {}, {"model": "openrouter/m:free"}),
            entry("a", {"input_cost_per_token": 9, "output_cost_per_token": 9}),  # duplicate
            {"model_name": 3},
            "junk",
        ]
    }
    assert parse_all(body) == [
        Listed("a", Prices(Decimal(1), Decimal(2)), "x/a"),
        Listed("b", None, "openrouter/m:free"),
    ]
    assert parse_all(None) == []


# --- remembering and noticing -------------------------------------------------------------


def test_the_first_look_records_and_a_new_price_is_noticed(sessions: sessionmaker[Session]) -> None:
    with sessions() as db:
        assert price_table.sync(db, [listed("big", "0.000003", "0.000015")]) == []
        assert price_table.sync(db, [listed("big", "0.000003", "0.000015")]) == []  # unchanged
        assert price_table.sync(db, [listed("big", "0.000004", "0.000015")]) == ["big"]
        (row,) = price_table.table(db)
    assert row["changed"] is True
    assert row["prompt_per_million_usd"] == "4" and row["previous_prompt_per_million_usd"] == "3"
    assert row["completion_per_million_usd"] == "15"
    assert row["free"] is False


def test_a_change_stops_being_warned_about_after_the_window(
    sessions: sessionmaker[Session],
) -> None:
    long_ago = datetime.now(UTC) - price_table.CHANGE_WINDOW - timedelta(days=1)
    with sessions() as db:
        price_table.sync(db, [listed("big", "1")], now=long_ago)
        price_table.sync(db, [listed("big", "2")], now=long_ago)
        (row,) = price_table.table(db)
        assert row["changed"] is False and row["previous_prompt_per_million_usd"] is None


def test_a_model_that_leaves_the_gateway_keeps_its_last_price(
    sessions: sessionmaker[Session],
) -> None:
    with sessions() as db:
        price_table.sync(db, [listed("big", "1")])
        price_table.sync(db, [])
        assert [r["model"] for r in price_table.table(db)] == ["big"]


def test_changed_models_come_first(sessions: sessionmaker[Session]) -> None:
    with sessions() as db:
        price_table.sync(db, [listed("a", "1"), listed("z", "1")])
        price_table.sync(db, [listed("a", "1"), listed("z", "2")])
        assert [r["model"] for r in price_table.table(db)] == ["z", "a"]
        assert [r["model"] for r in price_table.table(db, models={"a"})] == ["a"]


# --- free tiers ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("item", "free"),
    [
        (listed("zero", "0"), True),  # priced at zero by the gateway
        (listed("or", None, up="openrouter/meta/llama:free"), True),  # no price, free name
        (listed("openrouter-llama-3-free", "0.1"), True),  # a connection name cannot hold ":"
        (listed("paid", "0.1"), False),
        (listed("unpriced", None), False),
    ],
)
def test_free_means_zero_price_or_a_free_tier_name(
    sessions: sessionmaker[Session], item: Listed, free: bool
) -> None:
    with sessions() as db:
        price_table.sync(db, [item])
        row = db.get(ModelPrice, item.name)
    assert (row is not None and row.free) is free
    if row is None:
        assert item.name == "unpriced"  # nothing known, nothing recorded


def test_a_local_model_costs_nothing_but_is_not_a_free_tier(
    sessions: sessionmaker[Session],
) -> None:
    with sessions() as db:
        price_table.sync(db, [listed("coder", "0")], local={"coder"})
        assert price_table.table(db)[0]["free"] is False
        assert price_table.free_names(db) == set()


def test_free_calls_are_counted_in_the_project_costs(
    sessions: sessionmaker[Session],
    pid: uuid.UUID,  # noqa: F811
) -> None:
    with sessions() as db:
        price_table.sync(db, [listed("free-one", "0", up="vendor/m:free"), listed("big", "1")])
        db.add_all(
            [
                call(pid, None, "worker", "free-one", "0"),
                call(pid, None, "worker", "vendor/m:free", "0"),  # under the provider's name
                call(pid, None, "worker", "other:free", "0"),  # never listed, free by name
                call(pid, None, "worker", "big", "0.5"),
            ]
        )
        db.commit()
    body = client_for(sessions, pid).get(f"{API}/projects/{pid}/costs").json()
    assert body["free_calls"] == 3
    free = {m["model"]: m["free"] for m in body["by_model"]}
    assert free == {"big": False, "free-one": True, "vendor/m:free": True, "other:free": True}
    assert body["spent_usd"] == "0.50"


def test_a_recent_price_change_of_a_model_used_here_is_reported_with_the_costs(
    sessions: sessionmaker[Session],
    pid: uuid.UUID,  # noqa: F811
) -> None:
    with sessions() as db:
        price_table.sync(db, [listed("big", "1"), listed("unused", "1")])
        price_table.sync(db, [listed("big", "2"), listed("unused", "2")])
        db.add(call(pid, None, "worker", "big", "0.1"))
        db.commit()
    body = client_for(sessions, pid).get(f"{API}/projects/{pid}/costs").json()
    assert [p["model"] for p in body["price_changes"]] == ["big"]


# --- the API -------------------------------------------------------------------------------


class Book:
    def __init__(self, items: list[Listed]) -> None:
        self.items = items

    def prices(self, model: str) -> Prices | None:
        return next((i.prices for i in self.items if i.name == model), None)

    def listed(self) -> list[Listed]:
        return self.items


def test_the_price_view_refreshes_from_the_gateway_and_warns_of_a_change(
    sessions: sessionmaker[Session],
    pid: uuid.UUID,  # noqa: F811
) -> None:
    api = client_for(sessions, pid)
    book = Book([listed("big", "0.000001", "0.000002"), listed("f", None, up="v/m:free")])
    api.app.state.price_book = book  # type: ignore[attr-defined]
    first = api.get(f"{API}/models/prices").json()
    assert {p["model"]: p["free"] for p in first["prices"]} == {"big": False, "f": True}
    assert not any(p["changed"] for p in first["prices"])
    book.items[0] = listed("big", "0.000002", "0.000002")
    second = api.get(f"{API}/models/prices").json()
    assert second["prices"][0]["model"] == "big" and second["prices"][0]["changed"] is True
    assert second["prices"][0]["previous_prompt_per_million_usd"] == "1"
    assert second["change_window_days"] == 14


def test_the_price_view_needs_a_login_and_survives_a_dead_gateway(
    sessions: sessionmaker[Session],
    pid: uuid.UUID,  # noqa: F811
) -> None:
    assert client_for(sessions, None).get(f"{API}/models/prices").status_code == 401
    api = client_for(sessions, pid)

    class Broken:
        def listed(self) -> list[Listed]:
            raise RuntimeError("boom")

    api.app.state.price_book = Broken()  # type: ignore[attr-defined]
    reply = api.get(f"{API}/models/prices")
    assert reply.status_code == 200 and reply.json()["prices"] == []


# --- the CLI -------------------------------------------------------------------------------


class PriceRig:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    def table(self) -> list[dict[str, Any]]:
        return self.rows


def run_prices(rows: list[dict[str, Any]], lang: str = "en") -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    code = run(
        parse("prices"),
        Settings(lang=lang),
        api=FakeAPI(),
        term=Terminal(out, err, ask=lambda _q: "n"),
        prices=PriceRig(rows),
    )
    return code, out.getvalue(), err.getvalue()


ROWS = [
    {
        "model": "big",
        "prompt_per_million_usd": "4",
        "completion_per_million_usd": "15",
        "free": False,
        "changed": True,
        "previous_prompt_per_million_usd": "3",
        "previous_completion_per_million_usd": "15",
    },
    {
        "model": "f",
        "prompt_per_million_usd": "0",
        "completion_per_million_usd": "0",
        "free": True,
        "changed": False,
        "previous_prompt_per_million_usd": None,
        "previous_completion_per_million_usd": None,
    },
]


def test_the_cli_lists_prices_flags_free_tiers_and_warns() -> None:
    code, out, err = run_prices(ROWS)
    assert code == 0
    assert "big" in out and "price changed (was 3 / 15)" in out and "free tier" in out
    assert "Free tiers have rate limits" in out
    assert "price of 1 model(s) changed" in err
    _, out, _ = run_prices(ROWS, "fr")
    assert "palier gratuit" in out and "prix modifié" in out
    assert run_prices([])[1].startswith("No price known")


# --- rate limits ---------------------------------------------------------------------------


class Clock:
    now = 0.0

    def __call__(self) -> float:
        return self.now


def limited_router(gateway: Gateway, backoff: RateLimitBackoff) -> CostRouter:
    return CostRouter(  # type: ignore[arg-type]
        gateway,
        Budget(),
        {},
        "default",
        chain_for=lambda role: ["free", "paid"],
        backoff=backoff,
    )


def test_a_rate_limited_model_is_tried_last_until_its_wait_is_over() -> None:
    clock = Clock()
    backoff = RateLimitBackoff(base_s=30, max_s=100, clock=clock)
    gateway = Gateway({"free": GatewayError(429)})
    router = limited_router(gateway, backoff)
    assert router.chat(Role.WORKER, []).model == "paid"
    assert gateway.tried == ["free", "paid"]  # the 429 is seen, the chain still applies
    gateway.tried.clear()
    router.chat(Role.WORKER, [])
    assert gateway.tried == ["paid"]  # not asked again while it cools down
    clock.now = 31
    gateway.failures.clear()
    gateway.tried.clear()
    assert router.chat(Role.WORKER, []).model == "free"  # the wait is over: first again
    assert not backoff.cooling("free")


def test_the_wait_doubles_up_to_a_limit_and_is_forgotten_at_the_first_answer() -> None:
    clock = Clock()
    backoff = RateLimitBackoff(base_s=10, max_s=25, clock=clock)
    for expected in (10, 20, 25, 25):
        backoff.hit("m")
        clock.now += expected - 1
        assert backoff.cooling("m")
        clock.now += 1
        assert not backoff.cooling("m")
    backoff.hit("m")
    backoff.ok("m")
    assert not backoff.cooling("m")
    backoff.hit("m")
    clock.now += 11
    assert not backoff.cooling("m")  # back to the first step


def test_a_cooling_model_is_still_used_when_nothing_else_is_left() -> None:
    backoff = RateLimitBackoff(clock=Clock())
    backoff.hit("only")
    gateway = Gateway()
    router = CostRouter(  # type: ignore[arg-type]
        gateway, Budget(), {}, "default", chain_for=lambda role: ["only"], backoff=backoff
    )
    assert router.chat(Role.WORKER, []).model == "only"
    assert not backoff.cooling("only")


def test_other_failures_do_not_start_a_wait() -> None:
    backoff = RateLimitBackoff(clock=Clock())
    gateway = Gateway({"free": GatewayError(500)})
    limited_router(gateway, backoff).chat(Role.WORKER, [])
    assert not backoff.cooling("free")
    assert backoff.order(["a", "b"]) == ["a", "b"]
