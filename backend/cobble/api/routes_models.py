"""Model connections API: connect a language-model service with an API key, test it, choose the
default. Administrators only; the module-manager keeps the key (encrypted) and gives it to the
gateway. The key is accepted here and never returned by any route (ADR 0009).
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field, SecretStr

from cobble.benchmark import service as benchmarks
from cobble.benchmark.tasks import VERSION as BENCHMARK_VERSION
from cobble.db.models import PlatformState
from cobble.router import price_table
from cobble.router.gateway import LiteLLMGateway
from cobble.router.policy import MAX_CHAIN, ROLES, ModelPolicy
from cobble.router.presets import BY_ID, PRESETS, resolve

from .deps import AdminUser, AppSettings, CurrentUser, Db
from .errors import ApiError
from .routes_costs import sync_prices
from .routes_modules import Manager, _call

router = APIRouter()


class ModelBody(BaseModel):
    provider: str = Field(max_length=20)
    model: str = Field(max_length=100)
    api_key: SecretStr = Field(max_length=600)
    base_url: str | None = Field(default=None, max_length=300)
    make_default: bool = False


def get_gateway(request: Request, settings: AppSettings) -> LiteLLMGateway:
    injected = getattr(request.app.state, "gateway", None)  # tests
    if injected is not None:
        return injected  # type: ignore[no-any-return]
    return LiteLLMGateway(
        settings.litellm_url, settings.litellm_key, request.app.state.session_factory
    )


Gateway = Annotated[LiteLLMGateway, Depends(get_gateway)]


def _listing(body: dict[str, Any], configured_default: str) -> dict[str, Any]:
    """The manager's list plus what applies when none was chosen (`fake` in development)."""
    return {**body, "configured_default": configured_default}


class RoutesBody(BaseModel):
    routes: dict[str, list[str]] = Field(default_factory=dict, max_length=len(ROLES))


def _routes_view(policy: ModelPolicy) -> dict[str, Any]:
    return {
        "roles": [role.value for role in ROLES],
        "max_chain": MAX_CHAIN,
        "routes": policy.routes(),
        # What each role really uses now (a route, else the setting, else the default).
        "effective": {role.value: policy.chain_for(role) for role in ROLES},
    }


@router.get("/models/routes")
def get_routes(request: Request, _admin: AdminUser, settings: AppSettings) -> dict[str, Any]:
    return _routes_view(ModelPolicy(request.app.state.session_factory, settings))


def _known_models(listing: dict[str, Any], settings: Any) -> set[str]:
    """Names a route may use: the connections, the models served here, the built-in default."""
    names = {m["name"] for m in listing["models"]}
    names |= {m["name"] for m in listing.get("local", [])}
    return names | {settings.default_model}


def _store_routes(db: Any, routes: dict[str, list[str]]) -> None:
    state = db.get(PlatformState, 1)
    if state is None:
        state = PlatformState(id=1)
        db.add(state)
    state.role_routes = routes or None
    db.commit()


@router.put("/models/routes")
def put_routes(
    request: Request,
    body: RoutesBody,
    _admin: AdminUser,
    db: Db,
    manager: Manager,
    settings: AppSettings,
) -> dict[str, Any]:
    """Set, per role, the ordered models to try. A role left out or empty follows the default."""
    known = _known_models(_call(manager.models), settings)
    roles = {role.value for role in ROLES}
    bad = sorted(
        {f"routes.{role}" for role in body.routes if role not in roles}
        | {
            f"routes.{role}"
            for role, chain in body.routes.items()
            if len(chain) > MAX_CHAIN or any(name not in known for name in chain)
        }
    )
    if bad:
        raise ApiError(422, "validation_error", fields=bad)
    routes = {role: list(dict.fromkeys(chain)) for role, chain in body.routes.items() if chain}
    _store_routes(db, routes)
    return _routes_view(ModelPolicy(request.app.state.session_factory, settings))


# --- presets -----------------------------------------------------------------------------------


class SlotsBody(BaseModel):
    local: str | None = Field(default=None, max_length=60)
    cheap: str | None = Field(default=None, max_length=60)
    strong: str | None = Field(default=None, max_length=60)

    def as_slots(self) -> dict[str, str | None]:
        return {"local": self.local, "cheap": self.cheap, "strong": self.strong}


def _suggested_slots(listing: dict[str, Any], settings: Any) -> dict[str, str | None]:
    """What the slots default to: the first model served here, and the platform default for the
    strong one. `cheap` is left to the owner (it falls back to `strong`)."""
    local = listing.get("local", [])
    return {
        "local": local[0]["name"] if local else None,
        "cheap": None,
        "strong": listing.get("default") or settings.default_model,
    }


def _presets_view(
    listing: dict[str, Any], settings: Any, slots: dict[str, str | None]
) -> dict[str, Any]:
    out = []
    for preset in PRESETS:
        outcome = resolve(preset, slots)
        out.append(
            {
                "id": preset.id,
                "required": list(preset.required),
                "available": outcome.available,
                "missing": list(outcome.missing),
                "routes": outcome.routes,
            }
        )
    return {
        "slots": slots,
        "suggested": _suggested_slots(listing, settings),
        "local": [m["name"] for m in listing.get("local", [])],
        "models": sorted(_known_models(listing, settings)),
        "presets": out,
    }


def _checked_slots(
    listing: dict[str, Any], settings: Any, chosen: dict[str, str | None]
) -> dict[str, str | None]:
    """The owner's choices over the suggestions; a name nobody knows is a 422."""
    known = _known_models(listing, settings)
    slots = {**_suggested_slots(listing, settings), **{k: v for k, v in chosen.items() if v}}
    bad = sorted(f"slots.{slot}" for slot, name in slots.items() if name and name not in known)
    if bad:
        raise ApiError(422, "validation_error", fields=bad)
    return slots


@router.get("/models/presets")
def get_presets(
    _admin: AdminUser,
    manager: Manager,
    settings: AppSettings,
    local: str | None = None,
    cheap: str | None = None,
    strong: str | None = None,
) -> dict[str, Any]:
    """The presets, whether each can be applied, and the routes it would give for these slots."""
    listing = _call(manager.models)
    slots = _checked_slots(listing, settings, {"local": local, "cheap": cheap, "strong": strong})
    return _presets_view(listing, settings, slots)


@router.post("/models/presets/{preset_id}/apply")
def apply_preset(
    preset_id: str,
    request: Request,
    body: SlotsBody,
    _admin: AdminUser,
    db: Db,
    manager: Manager,
    settings: AppSettings,
) -> dict[str, Any]:
    """Replace the routes of every role by the preset's, filled with the chosen models."""
    preset = BY_ID.get(preset_id)
    if preset is None:
        raise ApiError(404, "preset_unknown", name=preset_id)
    listing = _call(manager.models)
    slots = _checked_slots(listing, settings, body.as_slots())
    outcome = resolve(preset, slots)
    if not outcome.available:
        raise ApiError(422, "preset_unavailable", missing=list(outcome.missing))
    _store_routes(db, outcome.routes)
    return _routes_view(ModelPolicy(request.app.state.session_factory, settings))


@router.get("/models/benchmarks")
def get_benchmarks(request: Request, _admin: AdminUser) -> dict[str, Any]:
    """The latest benchmark of each model (current task set), best first, and which model the
    benchmark proposes for the worker role. Runs are started with `cobble models benchmark`."""
    rows = benchmarks.latest(request.app.state.session_factory, BENCHMARK_VERSION)
    return {
        "version": BENCHMARK_VERSION,
        "results": [
            {
                "model": r.model,
                "quality": float(r.quality),
                "seconds": float(r.seconds),
                "tokens_per_second": (
                    float(r.tokens_per_second) if r.tokens_per_second is not None else None
                ),
                "created_at": r.created_at.isoformat(),
                "failed_tasks": sum(1 for o in r.outcomes if o["passed"] < o["total"]),
                "tasks": len(r.outcomes),
            }
            for r in rows
        ],
        "suggested_worker": benchmarks.best_worker(rows),
    }


@router.get("/models/prices")
def get_prices(
    request: Request, _user: CurrentUser, db: Db, settings: AppSettings
) -> dict[str, Any]:
    """The last price seen of each model (USD per million tokens), changed ones first, and
    which models are free tiers. Looking refreshes the table from the gateway (ADR 0013)."""
    sync_prices(request, settings, db)
    return {
        "prices": price_table.table(db),
        "change_window_days": price_table.CHANGE_WINDOW.days,
    }


@router.get("/models")
def list_models(_admin: AdminUser, manager: Manager, settings: AppSettings) -> dict[str, Any]:
    return _listing(_call(manager.models), settings.default_model)


@router.put("/models/{name}")
def put_model(
    name: str, body: ModelBody, _admin: AdminUser, manager: Manager, settings: AppSettings
) -> dict[str, Any]:
    payload = {
        "provider": body.provider,
        "model": body.model,
        "api_key": body.api_key.get_secret_value(),
        "base_url": body.base_url,
        "make_default": body.make_default,
    }
    return _listing(_call(lambda: manager.put_model(name, payload)), settings.default_model)


@router.delete("/models/{name}")
def delete_model(
    name: str, _admin: AdminUser, manager: Manager, settings: AppSettings
) -> dict[str, Any]:
    return _listing(_call(lambda: manager.delete_model(name)), settings.default_model)


@router.post("/models/{name}/default")
def make_default(
    name: str, _admin: AdminUser, manager: Manager, settings: AppSettings
) -> dict[str, Any]:
    return _listing(_call(lambda: manager.set_default_model(name)), settings.default_model)


@router.post("/models/{name}/test")
def test_model(name: str, _admin: AdminUser, manager: Manager, gateway: Gateway) -> dict[str, Any]:
    """Can the gateway reach this model with its key? A stable code, never the provider's words."""
    known = {m["name"] for m in _call(manager.models)["models"]}
    if name not in known:
        raise ApiError(404, "model_unknown", name=name)
    result = gateway.probe(name)
    return {"ok": result.ok, "code": result.code}
