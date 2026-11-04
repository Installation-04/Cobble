"""Per-token prices of a model, as the gateway knows them (for the savings counter).

Cobble keeps no price table of its own: the gateway (LiteLLM) already prices every call, so the
price of a model comes from its `/model/info`. A model the gateway cannot price (no entry, no
price, an unreachable gateway) has no price: callers show "not available" instead of a guess.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Prices:
    """USD per token."""

    prompt: Decimal
    completion: Decimal


def _price(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        price = Decimal(str(value))
    except InvalidOperation:
        return None
    return price if price.is_finite() and price >= 0 else None


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def parse_model_info(body: Any, model: str) -> Prices | None:
    """The prices of `model` in a `/model/info` body, or None when it has none.

    The gateway reports a custom price in `litellm_params` and the effective one in
    `model_info`; the effective one wins. A deployment that only has one of the two prices does
    not count (half a price is no price)."""
    entries = body.get("data") if isinstance(body, dict) else None
    if not isinstance(entries, list):
        return None
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("model_name") != model:
            continue
        info = _mapping(entry.get("model_info"))
        params = _mapping(entry.get("litellm_params"))
        prompt = _price(info.get("input_cost_per_token"))
        completion = _price(info.get("output_cost_per_token"))
        if prompt is None or completion is None:
            prompt = _price(params.get("input_cost_per_token"))
            completion = _price(params.get("output_cost_per_token"))
        if prompt is not None and completion is not None:
            return Prices(prompt, completion)
    return None


class PriceBook:
    """Asks the gateway for prices and remembers the answer for a few minutes."""

    def __init__(
        self,
        client: httpx.Client,
        *,
        ttl_s: float = 300.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._client = client
        self._ttl_s = ttl_s
        self._clock = clock
        self._body: Any = None
        self._fetched_at: float | None = None

    def _info(self) -> Any:
        now = self._clock()
        if self._fetched_at is not None and now - self._fetched_at < self._ttl_s:
            return self._body
        try:
            reply = self._client.get("/model/info", timeout=10.0)
            self._body = reply.json() if reply.status_code == 200 else None
        except (httpx.HTTPError, ValueError):
            self._body = None  # remembered too: an unreachable gateway is not asked at every call
        self._fetched_at = now
        return self._body

    def prices(self, model: str) -> Prices | None:
        return parse_model_info(self._info(), model)
