"""Model connections API: connect a language-model service with an API key, test it, choose the
default. Administrators only; the module-manager keeps the key (encrypted) and gives it to the
gateway. The key is accepted here and never returned by any route (ADR 0009).
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field, SecretStr

from cobble.router.gateway import LiteLLMGateway

from .deps import AdminUser, AppSettings
from .errors import ApiError
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
