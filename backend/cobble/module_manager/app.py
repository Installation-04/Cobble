"""The module-manager's internal HTTP API (ADR 0008). Reachable only on the internal network.

Same conventions as the agent-service: bearer token, `/healthz` open, errors shaped
`{"error": {"code", "params"}}` with stable codes the UI translates.
"""

from __future__ import annotations

import hmac
from typing import Annotated, Any, Literal

from cobble_sdk import (
    Conflict,
    DependencyCycle,
    Manifest,
    NeedsChoice,
    NeedsConfirmation,
    NoCompatibleVariant,
    NotInstalled,
    ResolveError,
    UnknownModule,
    Unsatisfiable,
    choose_variant,
    pack_fit,
    recommend,
)
from cobble_sdk.resolve import InvalidChoice
from fastapi import Depends, FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .disk_catalog import DiskCatalog
from .service import Busy, OperationController, OperationRequest, plan_to_json


class ServiceError(Exception):
    def __init__(self, status: int, code: str, **params: Any) -> None:
        super().__init__(code)
        self.status = status
        self.code = code
        self.params = params


def refusal(exc: ResolveError) -> ServiceError:
    """Map a planning refusal to a status, a stable code and the data the UI needs to ask again."""
    if isinstance(exc, NeedsChoice):
        return ServiceError(
            409, "module_needs_choice", capability=exc.capability, candidates=list(exc.candidates)
        )
    if isinstance(exc, NeedsConfirmation):
        return ServiceError(409, "module_needs_confirmation", cascade=list(exc.cascade))
    if isinstance(exc, Conflict):
        return ServiceError(
            409, "module_conflict", capability=exc.capability, modules=list(exc.modules)
        )
    if isinstance(exc, Unsatisfiable):
        return ServiceError(
            422, "module_unsatisfiable", module=exc.module, capability=exc.capability
        )
    if isinstance(exc, UnknownModule):
        return ServiceError(404, "module_unknown", module=exc.module)
    if isinstance(exc, NotInstalled):
        return ServiceError(404, "module_not_installed", module=exc.module)
    if isinstance(exc, InvalidChoice):
        return ServiceError(
            422, "module_invalid_choice", capability=exc.capability, module=exc.module
        )
    if isinstance(exc, DependencyCycle):
        return ServiceError(422, "module_cycle", modules=list(exc.modules))
    if isinstance(exc, NoCompatibleVariant):
        problems = [{"code": p.code, "needed": p.needed, "have": p.have} for p in exc.problems]
        return ServiceError(
            422, "module_no_compatible_variant", module=exc.module, problems=problems
        )
    return ServiceError(422, "module_invalid", detail=type(exc).__name__)


class OperationBody(BaseModel):
    action: Literal["install", "uninstall"]
    modules: list[str] = Field(min_length=1, max_length=20)
    choices: dict[str, str] = Field(default_factory=dict)
    replace: bool = False
    confirm_cascade: bool = False

    def to_request(self) -> OperationRequest:
        return OperationRequest(
            self.action, self.modules, self.choices, self.replace, self.confirm_cascade
        )


def _error(status: int, code: str, params: dict[str, Any] | None = None) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "params": params or {}}}, status_code=status)


def describe(
    manifest: Manifest, controller: OperationController, state: dict[str, Any] | None
) -> dict[str, Any]:
    """One catalogue entry: what the Store shows, with the verdict for this machine."""
    manager = controller.manager
    try:
        variant = choose_variant(manifest, manager.hardware)
        fits: dict[str, Any] = {
            "ok": True,
            "variant": variant.id if variant else None,
            "problems": [],
        }
    except NoCompatibleVariant as exc:
        fits = {
            "ok": False,
            "variant": None,
            "problems": [
                {"code": p.code, "needed": p.needed, "have": p.have} for p in exc.problems
            ],
        }
    return {
        "id": manifest.id,
        "name": manifest.name,
        "version": manifest.version,
        "category": manifest.category,
        "description": manifest.description.model_dump(),
        "license": manifest.license,
        "provides": [p.capability for p in manifest.provides],
        "requires": list(manifest.requires),
        "exclusive": list(manifest.exclusive),
        "variants": [v.id for v in manifest.variants],
        "web_ui": manifest.web_ui.model_dump() if manifest.web_ui else None,
        "settings": [s.model_dump() for s in manifest.settings],
        "secrets": list(manifest.secrets),
        "host_access": list(manifest.host_access),
        "offline": manifest.offline,
        "hardware": fits,
        "installed": state,
    }


def create_app(
    controller: OperationController, token: str, catalog: DiskCatalog | None = None
) -> FastAPI:
    secret = token.encode()
    app = FastAPI(title="Cobble module-manager", docs_url=None, redoc_url=None)

    def require_token(authorization: Annotated[str | None, Header()] = None) -> None:
        scheme, _, value = (authorization or "").partition(" ")
        if (
            scheme.lower() != "bearer"
            or not secret
            or not hmac.compare_digest(value.strip().encode(), secret)
        ):
            raise ServiceError(401, "unauthorized")

    auth = Depends(require_token)

    @app.exception_handler(ServiceError)
    async def _service_error(_request: Request, exc: ServiceError) -> JSONResponse:
        return _error(exc.status, exc.code, exc.params)

    @app.exception_handler(RequestValidationError)
    async def _invalid(_request: Request, exc: RequestValidationError) -> JSONResponse:
        fields = [".".join(str(p) for p in e["loc"][1:]) for e in exc.errors()]
        return _error(422, "invalid_request", {"fields": fields})

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/v1/catalog", dependencies=[auth])
    def get_catalog() -> dict[str, Any]:
        manager = controller.manager
        states = manager.states()
        modules = [
            describe(manifest, controller, states.get(module_id))
            for module_id, manifest in sorted(manager.catalog().items())
        ]
        return {
            "modules": modules,
            "problems": catalog.problems() if catalog is not None else {},
            "hardware": {"ram_mb": manager.hardware.ram_mb, "gpu": manager.hardware.gpu},
        }

    @app.get("/v1/packs", dependencies=[auth])
    def get_packs() -> dict[str, Any]:
        """The starter packs: what each contains, whether it fits this machine, which one is
        proposed first, and how much of it is already installed."""
        if catalog is None:
            return {"packs": [], "problems": {}, "recommended": None}
        packs, problems = catalog.packs()
        manager = controller.manager
        manifests = manager.catalog()
        states = manager.states()
        recommended = recommend(packs, manifests, manager.hardware)
        entries = []
        for pack in sorted(packs.values(), key=lambda p: (-p.priority, p.id)):
            fit = pack_fit(pack, manifests, manager.hardware)
            running = [m for m in pack.modules if states.get(m, {}).get("state") == "running"]
            entries.append(
                {
                    "id": pack.id,
                    "name": pack.name.model_dump(),
                    "description": pack.description.model_dump(),
                    "modules": list(pack.modules),
                    "hardware": pack.hardware.model_dump(),
                    "priority": pack.priority,
                    "fit": {
                        "ok": fit.ok,
                        "problems": [
                            {"module": p.module, "code": p.code, "needed": p.needed, "have": p.have}
                            for p in fit.problems
                        ],
                    },
                    "recommended": pack.id == recommended,
                    "installed": len(running) == len(pack.modules),
                    "installed_modules": running,
                }
            )
        return {"packs": entries, "problems": problems, "recommended": recommended}

    @app.post("/v1/plan", dependencies=[auth])
    def post_plan(body: OperationBody) -> dict[str, Any]:
        try:
            return plan_to_json(controller.preview(body.to_request()))
        except ResolveError as exc:
            raise refusal(exc) from None

    @app.post("/v1/operations", status_code=202, dependencies=[auth])
    def post_operation(body: OperationBody) -> dict[str, Any]:
        try:
            operation = controller.submit(body.to_request())
        except Busy:
            raise ServiceError(409, "module_busy") from None
        except ResolveError as exc:
            raise refusal(exc) from None
        return {"operation_id": operation.id}

    @app.get("/v1/operations/{operation_id}", dependencies=[auth])
    def get_operation(operation_id: str) -> dict[str, Any]:
        operation = controller.get(operation_id)
        if operation is None:
            raise ServiceError(404, "not_found")
        return operation.as_dict()

    @app.get("/v1/connections", dependencies=[auth])
    def get_connections() -> dict[str, Any]:
        return {"connections": controller.manager.connections()}

    @app.get("/v1/modules/{module_id}/secrets", dependencies=[auth])
    def get_secret_status(module_id: str) -> dict[str, bool]:
        try:
            return controller.manager.secret_status(module_id)
        except UnknownModule as exc:
            raise refusal(exc) from None

    return app
