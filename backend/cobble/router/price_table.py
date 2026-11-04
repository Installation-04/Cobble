"""The table of model prices: the last price seen, what changed, and which models are free.

The gateway (LiteLLM) is the only source of prices (`prices.py`). This module remembers the last
one seen per model so a provider's price change is noticed and shown (ADR 0013). It never
reorders a route: the owner's chains are theirs, a change only raises a warning.

A model is *free* when the gateway prices it at zero or when its name is a free tier of a
provider (OpenRouter's `:free` models). A model served on this machine also costs nothing but
is not a free tier: callers pass the local names and those are never marked free.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from cobble.db.models import ModelPrice

from .prices import Listed, Prices

CHANGE_WINDOW = timedelta(days=14)  # how long a price change keeps being warned about
_PLACES = Decimal("0.000000000001")  # the column keeps 12 decimals


def has_free_name(*names: str | None) -> bool:
    """`vendor/model:free` (OpenRouter). The connection name of such a model, which cannot hold
    a colon, ends in `-free` after the `openrouter-` prefix."""
    for name in names:
        if not name:
            continue
        lowered = name.lower()
        if lowered.endswith(":free") or (
            lowered.startswith("openrouter-") and lowered.endswith("-free")
        ):
            return True
    return False


def is_free(prices: Prices | None, *names: str | None) -> bool:
    if prices is not None and prices.prompt == 0 and prices.completion == 0:
        return True
    return has_free_name(*names)


def _q(value: Decimal) -> Decimal:
    return value.quantize(_PLACES)


def sync(
    db: Session,
    listed: Iterable[Listed],
    *,
    local: Collection[str] = (),
    now: datetime | None = None,
) -> list[str]:
    """Record the prices just seen. Returns the models whose price changed since the last look.

    A model with no price is only recorded when it is a free tier (priced at zero then); a
    model that left the gateway keeps its last row."""
    now = now or datetime.now(UTC)
    changed: list[str] = []
    for item in listed:
        prices = item.prices
        if prices is None:
            if not has_free_name(item.name, item.upstream):
                continue
            prices = Prices(Decimal(0), Decimal(0))
        prompt, completion = _q(prices.prompt), _q(prices.completion)
        free = item.name not in local and is_free(prices, item.name, item.upstream)
        row = db.get(ModelPrice, item.name)
        if row is None:
            db.add(
                ModelPrice(
                    model=item.name,
                    upstream=item.upstream,
                    prompt_usd=prompt,
                    completion_usd=completion,
                    free=free,
                    updated_at=now,
                )
            )
            continue
        if _q(Decimal(row.prompt_usd)) != prompt or _q(Decimal(row.completion_usd)) != completion:
            row.previous_prompt_usd = row.prompt_usd
            row.previous_completion_usd = row.completion_usd
            row.prompt_usd, row.completion_usd = prompt, completion
            row.changed_at = now
            changed.append(item.name)
        row.upstream, row.free, row.updated_at = item.upstream, free, now
    db.commit()
    return changed


def _aware(value: datetime | None) -> datetime | None:
    return value.replace(tzinfo=UTC) if value is not None and value.tzinfo is None else value


def _per_million(value: Decimal | None) -> str | None:
    return None if value is None else format((Decimal(value) * 1_000_000).normalize(), "f")


def _view(row: ModelPrice, now: datetime) -> dict[str, Any]:
    changed_at = _aware(row.changed_at)
    recent = changed_at is not None and now - changed_at <= CHANGE_WINDOW
    return {
        "model": row.model,
        "prompt_per_million_usd": _per_million(row.prompt_usd),
        "completion_per_million_usd": _per_million(row.completion_usd),
        "free": bool(row.free),
        "changed": recent,
        "previous_prompt_per_million_usd": _per_million(row.previous_prompt_usd)
        if recent
        else None,
        "previous_completion_per_million_usd": (
            _per_million(row.previous_completion_usd) if recent else None
        ),
        "changed_at": changed_at.isoformat() if recent and changed_at else None,
    }


def table(db: Session, *, models: Collection[str] | None = None) -> list[dict[str, Any]]:
    """The remembered prices (per million tokens), changed ones first, then by name."""
    now = datetime.now(UTC)
    rows = db.scalars(select(ModelPrice)).all()
    views = [_view(r, now) for r in rows if models is None or r.model in models]
    return sorted(views, key=lambda v: (not v["changed"], v["model"]))


def free_names(db: Session) -> set[str]:
    """Every name a free model can show up under in `llm_calls` (connection or provider name)."""
    names: set[str] = set()
    for row in db.scalars(select(ModelPrice).where(ModelPrice.free.is_(True))):
        names.add(row.model)
        if row.upstream:
            names.add(row.upstream)
    return names
