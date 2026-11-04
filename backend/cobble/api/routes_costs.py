"""Costs API (ADR 0007): what the LLM calls cost, per project and across projects."""

from __future__ import annotations

import logging
from typing import Annotated, Any, Literal

import httpx
from fastapi import APIRouter, Query, Request, Response

from cobble import costs, report
from cobble.capabilities.llm import Role
from cobble.router import price_table
from cobble.router.factory import _local_models
from cobble.router.policy import ModelPolicy
from cobble.router.prices import PriceBook, Prices

from .deps import AppSettings, CurrentUser, Db, OwnedProject

log = logging.getLogger(__name__)
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


def sync_prices(request: Request, settings: Any, db: Any) -> None:
    """Remember the prices the gateway reports now (cached a few minutes) and notice changes.
    Best effort: a gateway or a database that fails must not break a report."""
    try:
        state = request.app.state
        local = getattr(state, "local_models", None)
        if local is None:
            local = state.local_models = _local_models(settings)
        listed = getattr(price_book(request, settings), "listed", None)
        if listed is not None:
            price_table.sync(db, listed(), local=local())
    except Exception:
        db.rollback()
        log.warning("cannot update the table of model prices", exc_info=True)


def reference(request: Request, settings: Any) -> tuple[str, Prices] | None:
    """The strongest model the owner configured (first of the escalation chain) and its prices."""
    model = ModelPolicy(request.app.state.session_factory, settings).chain_for(Role.ESCALATION)[0]
    prices = price_book(request, settings).prices(model)
    return (model, prices) if prices is not None else None


@router.get("/projects/{project_id}/costs")
def project_costs(
    request: Request, project: OwnedProject, db: Db, settings: AppSettings
) -> dict[str, Any]:
    sync_prices(request, settings, db)
    return costs.project_costs(db, project, reference(request, settings))


@router.get("/costs")
def all_costs(user: CurrentUser, db: Db) -> list[dict[str, Any]]:
    return costs.global_costs(db, user.id)


@router.get("/projects/{project_id}/report", response_model=None)
def project_report(
    request: Request,
    project: OwnedProject,
    user: CurrentUser,
    db: Db,
    settings: AppSettings,
    format: Annotated[Literal["json", "md"], Query()] = "json",
) -> Any:
    """End-of-project report (ADR 0014): JSON, or a Markdown download in the user's language."""
    body = report.project_report(db, project, reference(request, settings))
    if format == "json":
        return body
    return Response(
        report.render_markdown(body, user.lang),
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{report.filename(project.name)}"',
            "Cache-Control": "no-store",
        },
    )
