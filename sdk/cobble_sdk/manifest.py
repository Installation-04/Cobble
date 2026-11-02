"""The module manifest (PLAN.md section 6): schema and validation.

A manifest describes what a module provides and needs, never how the platform enforces its
rules: port publishing, namespaces, networks and limits are applied by the module-manager and
cannot be chosen here. Unknown fields are rejected, so a typo is an error, not a silent no-op.
"""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath
from typing import Annotated, Any, Literal

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    field_validator,
    model_validator,
)

MODULE_ID = r"^[a-z][a-z0-9-]{1,39}$"
CAPABILITY = r"^[a-z][a-z0-9-]{0,39}$"
KEY = r"^[a-z][a-z0-9_]{0,39}$"
VERSION = r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$"
DURATION = r"^\d+(?:ms|s|m)$"
DIGEST_IMAGE = re.compile(r"^[a-z0-9][a-z0-9./_-]*(?::[A-Za-z0-9_.-]+)?@sha256:[0-9a-f]{64}$")

ModuleId = Annotated[str, StringConstraints(pattern=MODULE_ID)]
Capability = Annotated[str, StringConstraints(pattern=CAPABILITY)]
Key = Annotated[str, StringConstraints(pattern=KEY)]
Duration = Annotated[str, StringConstraints(pattern=DURATION)]
GpuKind = Literal["none", "optional", "nvidia", "amd", "any"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Localized(_Strict):
    """A user-visible text in both supported languages."""

    fr: str = Field(min_length=1)
    en: str = Field(min_length=1)


class Provide(_Strict):
    """A capability the module provides, and the core adapter that speaks to it."""

    capability: Capability
    adapter: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9-]*$")


class Hardware(_Strict):
    min_ram_mb: int = Field(default=0, ge=0)
    gpu: GpuKind = "none"


class LlmModel(_Strict):
    """A model a language-model backend serves, as the router will see it."""

    # The name clients use through the gateway.
    name: Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9._:/-]{0,79}$")]
    # The gateway's own model string: provider prefix and the backend's model name.
    model: Annotated[str, StringConstraints(pattern=r"^[a-z0-9_]+/[A-Za-z0-9._:/-]{1,100}$")]
    # What the module's hook must fetch before the model can answer (backend-native name).
    pull: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9._:/-]{1,100}$")] | None = None


class Variant(_Strict):
    """A hardware-specific flavour of a module (for example Ollama CPU, NVIDIA, AMD)."""

    id: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9-]{0,19}$")]
    gpu: GpuKind = "none"
    min_ram_mb: int = Field(default=0, ge=0)
    # Models served by this flavour instead of the module's default ones (a small model on CPU,
    # a larger one on a GPU).
    models: list[LlmModel] | None = None
    # A compose file for this flavour instead of the module's (GPU access differs per vendor).
    compose: str | None = None

    @field_validator("compose")
    @classmethod
    def _compose_path(cls, value: str | None) -> str | None:
        return None if value is None else _safe_relative_path(value)


SERVICE = r"^[a-z0-9][a-z0-9_.-]{0,62}$"
ServiceName = Annotated[str, StringConstraints(pattern=SERVICE)]


class WebUi(_Strict):
    service: ServiceName
    port: int = Field(ge=1, le=65535)
    path: str = Field(pattern=r"^/[A-Za-z0-9._~/-]*$")
    # True: the proxy removes `path` before forwarding (the product lives at its root);
    # False: the product is configured for the prefix and expects to see it.
    strip_prefix: bool = True
    # False: the service is reachable on the platform network only (the core talks to it); no
    # route is published on the reverse proxy and the Store shows no link.
    public: bool = True

    @field_validator("path")
    @classmethod
    def _no_traversal(cls, value: str) -> str:
        if ".." in value.split("/"):
            raise ValueError("path must not contain '..'")
        return value


class Llm(_Strict):
    """Where a language-model backend listens and which models it serves by default."""

    service: ServiceName
    port: int = Field(ge=1, le=65535)
    models: list[LlmModel] = Field(default_factory=list)


class Setting(_Strict):
    key: Key
    type: Literal["text", "email", "number", "bool", "select"] = "text"
    default: str | int | float | bool | None = None
    required: bool = False
    options: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _select_needs_options(self) -> Setting:
        if self.type == "select" and not self.options:
            raise ValueError("a 'select' setting needs options")
        if self.type != "select" and self.options:
            raise ValueError("options are only allowed on a 'select' setting")
        if self.type == "select" and self.default is not None and self.default not in self.options:
            raise ValueError("the default must be one of the options")
        return self


class Healthcheck(_Strict):
    http: str = Field(pattern=r"^/[A-Za-z0-9._~/?=&%-]*$")
    interval: Duration = "10s"
    timeout: Duration = "5s"


def _safe_relative_path(value: str) -> str:
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or not value.strip():
        raise ValueError("must be a relative path inside the module")
    return value


class Hooks(_Strict):
    """Shell hooks, relative to the module directory. All must be idempotent."""

    # Runs before the module starts, once the modules it requires are running (it can prepare
    # what the module needs from them, for example an OAuth application); the secrets it
    # prints become the module's own and are available when the compose file is rendered.
    pre_up: str | None = None
    post_install: str | None = None
    register_core: str | None = None
    pre_uninstall: str | None = None
    on_link: dict[Capability, str] = Field(default_factory=dict)
    on_unlink: dict[Capability, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _paths(self) -> Hooks:
        for value in (self.pre_up, self.post_install, self.register_core, self.pre_uninstall):
            if value is not None:
                _safe_relative_path(value)
        for value in (*self.on_link.values(), *self.on_unlink.values()):
            _safe_relative_path(value)
        return self


class Backup(_Strict):
    volumes: list[Key] = Field(default_factory=list)


class Manifest(_Strict):
    id: ModuleId
    name: str = Field(min_length=1, max_length=60)
    version: Annotated[str, StringConstraints(pattern=VERSION)]
    category: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9-]{0,29}$")]
    description: Localized
    license: str = Field(min_length=1, max_length=80)
    provides: list[Provide] = Field(default_factory=list)
    requires: list[Capability] = Field(default_factory=list)
    exclusive: list[Capability] = Field(default_factory=list)
    hardware: Hardware = Field(default_factory=Hardware)
    variants: list[Variant] = Field(default_factory=list)
    compose: str = "compose.yml"
    images: list[str] = Field(min_length=1)
    host_access: list[Literal["docker_socket"]] = Field(default_factory=list)
    web_ui: WebUi | None = None
    # A module that provides `llm-backend` says where it listens; the platform adds its models
    # to the language-model gateway.
    llm: Llm | None = None
    # Compose services that join the shared platform network (the web_ui service always does).
    bus: list[ServiceName] = Field(default_factory=list)
    settings: list[Setting] = Field(default_factory=list)
    secrets: list[Key] = Field(default_factory=list)
    # Secrets (declared above or produced by a hook) that the core may read to talk to the module,
    # for example the API token of a Git server. Nothing else leaves the vault.
    core_secrets: list[Key] = Field(default_factory=list)
    # Secrets the hooks of a module that requires this one may read, as COBBLE_PEER_* variables
    # (for example the service account of a Git server, so that a CI module can sign in). They
    # never reach the core, the API or the browser.
    link_secrets: list[Key] = Field(default_factory=list)
    healthcheck: Healthcheck | None = None
    hooks: Hooks = Field(default_factory=Hooks)
    backup: Backup = Field(default_factory=Backup)
    offline: bool = False

    def llm_models(self, variant: str | None = None) -> list[LlmModel]:
        """The models served by `variant` (or the module's default ones)."""
        if self.llm is None:
            return []
        for candidate in self.variants:
            if candidate.id == variant and candidate.models is not None:
                return list(candidate.models)
        return list(self.llm.models)

    @field_validator("provides", mode="before")
    @classmethod
    def _shorthand(cls, value: Any) -> Any:
        """`provides: [git]` is shorthand for `[{capability: git}]`."""
        if isinstance(value, list):
            return [{"capability": item} if isinstance(item, str) else item for item in value]
        return value

    @field_validator("compose")
    @classmethod
    def _compose_path(cls, value: str) -> str:
        return _safe_relative_path(value)

    @field_validator("images")
    @classmethod
    def _images_pinned(cls, value: list[str]) -> list[str]:
        for image in value:
            if not DIGEST_IMAGE.match(image):
                raise ValueError(f"image {image!r} must be pinned by digest (name@sha256:<64 hex>)")
            if re.search(r":latest(?:@|$)", image):
                raise ValueError(f"image {image!r} must not use the 'latest' tag")
        return value

    @model_validator(mode="after")
    def _consistency(self) -> Manifest:
        provided = [p.capability for p in self.provides]
        _unique(provided, "provides")
        _unique(self.requires, "requires")
        _unique(self.exclusive, "exclusive")
        _unique([s.key for s in self.settings], "settings")
        _unique(self.secrets, "secrets")
        _unique(self.core_secrets, "core_secrets")
        _unique(self.link_secrets, "link_secrets")
        _unique([v.id for v in self.variants], "variants")
        _unique(self.images, "images")
        _unique(self.backup.volumes, "backup.volumes")
        _unique(self.bus, "bus")
        if self.llm is not None and "llm-backend" not in provided:
            raise ValueError("'llm' needs the module to provide 'llm-backend'")
        if self.llm is None and any(v.models is not None for v in self.variants):
            raise ValueError("variant 'models' need an 'llm' block")
        if self.llm is not None:
            _unique([m.name for m in self.llm.models], "llm models")
            for variant in self.variants:
                if variant.models is not None:
                    _unique([m.name for m in variant.models], f"llm models of {variant.id}")
        if set(self.exclusive) - set(provided):
            raise ValueError("'exclusive' may only list capabilities the module provides")
        if set(self.requires) & set(provided):
            raise ValueError("a module cannot require a capability it provides")
        if {s.key for s in self.settings} & set(self.secrets):
            raise ValueError("a key cannot be both a setting and a secret")
        return self


def _unique(values: list[str], field: str) -> None:
    seen: set[str] = set()
    for value in values:
        if value in seen:
            raise ValueError(f"duplicate entry in {field}: {value!r}")
        seen.add(value)


class ManifestError(ValueError):
    """The manifest is invalid. `problems` lists `location: message` lines, one per defect."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


def parse_manifest(data: object) -> Manifest:
    """Validate an already-loaded manifest (a mapping)."""
    if not isinstance(data, dict):
        raise ManifestError(["<root>: a manifest must be a mapping"])
    try:
        return Manifest.model_validate(data)
    except ValidationError as exc:
        problems = [
            f"{'.'.join(str(part) for part in err['loc']) or '<root>'}: {err['msg']}"
            for err in exc.errors()
        ]
        raise ManifestError(problems) from None


def load_manifest(path: Path | str) -> Manifest:
    """Read and validate a YAML manifest file."""
    try:
        data = yaml.safe_load(Path(path).read_text("utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ManifestError([f"<file>: {exc}"]) from None
    return parse_manifest(data)


def manifest_json_schema() -> dict[str, Any]:
    """The JSON Schema of the manifest, for editors and the catalogue lint."""
    schema = Manifest.model_json_schema()
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["title"] = "Cobble module manifest"
    return schema
