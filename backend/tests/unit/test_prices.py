"""Prices come from the gateway's /model/info; nothing is guessed."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import httpx
import pytest

from cobble.router.prices import PriceBook, Prices, parse_model_info


def entry(
    name: str, info: dict[str, Any] | None = None, params: dict[str, Any] | None = None
) -> Any:
    return {"model_name": name, "model_info": info or {}, "litellm_params": params or {}}


def test_the_effective_price_of_the_model_is_read() -> None:
    body = {
        "data": [
            entry("other", {"input_cost_per_token": 9, "output_cost_per_token": 9}),
            entry("fake", {"input_cost_per_token": 1e-06, "output_cost_per_token": 2e-06}),
        ]
    }
    assert parse_model_info(body, "fake") == Prices(Decimal("0.000001"), Decimal("0.000002"))


def test_a_custom_price_in_the_parameters_is_used_when_the_info_has_none() -> None:
    body = {"data": [entry("fake", {}, {"input_cost_per_token": 0.5, "output_cost_per_token": 1})]}
    assert parse_model_info(body, "fake") == Prices(Decimal("0.5"), Decimal("1"))


def test_a_free_model_has_a_price_of_zero_not_no_price() -> None:
    body = {"data": [entry("coder", {"input_cost_per_token": 0, "output_cost_per_token": 0})]}
    assert parse_model_info(body, "coder") == Prices(Decimal(0), Decimal(0))


@pytest.mark.parametrize(
    "body",
    [
        None,
        {},
        {"data": "nope"},
        {"data": [entry("fake")]},  # known, but not priced
        {"data": [entry("fake", {"input_cost_per_token": 1})]},  # half a price is no price
        {"data": [entry("fake", {"input_cost_per_token": -1, "output_cost_per_token": 1})]},
        {"data": [entry("fake", {"input_cost_per_token": "x", "output_cost_per_token": 1})]},
        {"data": [entry("fake", {"input_cost_per_token": True, "output_cost_per_token": 1})]},
        {"data": [entry("elsewhere", {"input_cost_per_token": 1, "output_cost_per_token": 1})]},
        {"data": ["junk", 3]},
    ],
)
def test_what_cannot_be_priced_has_no_price(body: Any) -> None:
    assert parse_model_info(body, "fake") is None


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def book(handler: Any, clock: Clock) -> PriceBook:
    client = httpx.Client(transport=httpx.MockTransport(handler), base_url="http://litellm")
    return PriceBook(client, ttl_s=300, clock=clock)


GOOD = {"data": [entry("fake", {"input_cost_per_token": 1, "output_cost_per_token": 2})]}


def test_the_gateway_is_asked_once_per_ttl() -> None:
    asked: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        asked.append(request.url.path)
        return httpx.Response(200, json=GOOD)

    clock = Clock()
    prices = book(handler, clock)
    assert prices.prices("fake") == Prices(Decimal(1), Decimal(2))
    assert prices.prices("fake") is not None and prices.prices("nope") is None
    assert asked == ["/model/info"]
    clock.now = 301
    prices.prices("fake")
    assert len(asked) == 2


@pytest.mark.parametrize("failure", ["status", "transport", "body"])
def test_an_unhelpful_gateway_means_no_price_and_no_exception(failure: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if failure == "transport":
            raise httpx.ConnectError("down")
        if failure == "status":
            return httpx.Response(500)
        return httpx.Response(200, content=b"not json")

    assert book(handler, Clock()).prices("fake") is None
