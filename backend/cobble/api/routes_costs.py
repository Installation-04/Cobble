"""Costs API (ADR 0007): what the LLM calls cost, per project and across projects."""

from __future__ import annotations

from typing import Any

import httpx
from fastapi import APIRouter, Request

from cobble import costs
from cobble.capabilities.llm import Role
from cobble.router.policy import ModelPolicy
from cobble.router.prices import PriceBook, Prices

from .deps import AppSettings, CurrentUser, Db, OwnedProject

router = APIRouter()


def price_book(request: Request, settings: Any) -> PriceBook:
    """The gateway's prices, asked lazily and remembered (tests put their own on the app)."""
    state = request.app.state
    book = getattr(state, "price_book", None)
    if book is None:
        headers = (
            {"Authorization": f"Bearer {settings.litellm_key}"} if settings.litellm_key else {}
        )
        book = PriceBook(httpx.Client(base_url=settings.litellm_url.rstrip("/"), headers=headers))
        state.price_book = book
    return book


def reference(request: Request, settings: Any) -> tuple[str, Prices] | None:
    """The strongest model the owner configured (first of the escalation chain) and its prices."""
    model = ModelPolicy(request.app.state.session_factory, settings).chain_for(Role.ESCALATION)[0]
    prices = price_book(request, settings).prices(model)
    return (model, prices) if prices is not None else None


@router.get("/projects/{project_id}/costs")
def project_costs(
    request: Request, project: OwnedProject, db: Db, settings: AppSettings
) -> dict[str, Any]:
    return costs.project_costs(db, project, reference(request, settings))


@router.get("/costs")
def all_costs(user: CurrentUser, db: Db) -> list[dict[str, Any]]:
    return costs.global_costs(db, user.id)
