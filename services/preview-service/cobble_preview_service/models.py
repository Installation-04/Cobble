"""Request and response models of the preview-service HTTP API (ADR 0007)."""

from __future__ import annotations

import re
import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator

from .gitops import valid_ref

_MILESTONE = re.compile(r"^M\d{1,4}$")

PublicState = Literal["building", "running", "failed"]


def valid_milestone(value: str) -> bool:
    return bool(_MILESTONE.match(value))


class PreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: uuid.UUID
    milestone: str
    repo_clone_url: str
    ref: str

    @field_validator("milestone")
    @classmethod
    def _milestone(cls, value: str) -> str:
        if not valid_milestone(value):
            raise ValueError("invalid milestone")
        return value

    @field_validator("ref")
    @classmethod
    def _ref(cls, value: str) -> str:
        if not valid_ref(value):
            raise ValueError("invalid ref")
        return value

    @field_validator("repo_clone_url")
    @classmethod
    def _url(cls, value: str) -> str:
        if not value.startswith(("http://", "https://", "file://")) or len(value) > 500:
            raise ValueError("invalid repository url")
        return value

    @property
    def id(self) -> str:
        return f"{self.project_id}-{self.milestone}"


class PreviewOut(BaseModel):
    id: str
    project_id: str
    milestone: str
    ref: str
    state: PublicState
    path: str
    detail: str = ""
    idle: bool = False
