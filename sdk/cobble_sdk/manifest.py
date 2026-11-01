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


class Variant(_Strict):
    """A hardware-specific flavour of a module (for example Ollama CPU, NVIDIA, AMD)."""

    id: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9-]{0,19}$")]
    gpu: GpuKind = "none"
    min_ram_mb: int = Field(default=0, ge=0)


class WebUi(_Strict):
    port: int = Field(ge=1, le=65535)
    path: str = Field(pattern=r"^/[A-Za-z0-9._~/-]*$")

    @field_validator("path")
    @classmethod
    def _no_traversal(cls, value: str) -> str:
        if ".." in value.split("/"):
            raise ValueError("path must not contain '..'")
        return value


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

    post_install: str | None = None
    register_core: str | None = None
    pre_uninstall: str | None = None
    on_link: dict[Capability, str] = Field(default_factory=dict)
    on_unlink: dict[Capability, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _paths(self) -> Hooks:
        for value in (self.post_install, self.register_core, self.pre_uninstall):
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
    settings: list[Setting] = Field(default_factory=list)
    secrets: list[Key] = Field(default_factory=list)
    healthcheck: Healthcheck | None = None
    hooks: Hooks = Field(default_factory=Hooks)
    backup: Backup = Field(default_factory=Backup)
    offline: bool = False

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
        _unique([v.id for v in self.variants], "variants")
        _unique(self.images, "images")
        _unique(self.backup.volumes, "backup.volumes")
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
