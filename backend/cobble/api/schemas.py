"""Request and response bodies."""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from cobble.auth.passwords import MIN_PASSWORD_LENGTH

Lang = Literal["fr", "en"]
Theme = Literal["system", "light", "dark"]
Phase = Literal["interview", "spec_review", "plan_review", "ready", "building", "done"]
Approval = Literal["draft", "approved"]

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _name(value: str) -> str:
    value = value.strip()
    if not 1 <= len(value) <= 100:
        raise ValueError("name must be 1-100 characters")
    return value


def _email(value: str) -> str:
    value = value.strip().lower()
    if len(value) > 254 or not _EMAIL.match(value):
        raise ValueError("invalid email")
    return value


class ActivateIn(BaseModel):
    token: str
    email: str
    password: str
    lang: Lang | None = None

    _check_email = field_validator("email")(_email)

    @field_validator("password")
    @classmethod
    def _password(cls, value: str) -> str:
        if not MIN_PASSWORD_LENGTH <= len(value) <= 256:
            raise ValueError("password length")
        return value


class LoginIn(BaseModel):
    email: str
    password: str

    @field_validator("email")
    @classmethod
    def _email_lower(cls, value: str) -> str:
        return value.strip().lower()

    @field_validator("password")
    @classmethod
    def _password(cls, value: str) -> str:
        if len(value) > 1024:
            raise ValueError("password too long")
        return value


class MePatch(BaseModel):
    lang: Lang | None = None
    theme: Theme | None = None


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    role: Literal["admin"]
    lang: Lang
    theme: Theme


class SetupStatus(BaseModel):
    initialized: bool


class FolderIn(BaseModel):
    name: str

    _check_name = field_validator("name")(_name)


class FolderPatch(BaseModel):
    name: str | None = None

    @field_validator("name")
    @classmethod
    def _check_name(cls, value: str | None) -> str:
        if value is None:
            raise ValueError("name cannot be null")
        return _name(value)


class FolderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    position: int


class ProjectIn(BaseModel):
    name: str
    folder_id: uuid.UUID | None = None

    _check_name = field_validator("name")(_name)


class ProjectPatch(BaseModel):
    name: str | None = None
    folder_id: uuid.UUID | None = None
    budget_usd: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)

    @field_validator("name")
    @classmethod
    def _check_name(cls, value: str | None) -> str:
        if value is None:
            raise ValueError("name cannot be null")
        return _name(value)


class ProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    folder_id: uuid.UUID | None
    created_at: datetime
    budget_usd: Decimal | None
    status: Literal["active", "paused"]
    phase: Phase


class MessageIn(BaseModel):
    content: str

    @field_validator("content")
    @classmethod
    def _content(cls, value: str) -> str:
        value = value.strip()
        if not 1 <= len(value) <= 8000:
            raise ValueError("content must be 1-8000 characters")
        return value


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    role: Literal["user", "assistant"]
    content: str
    created_at: datetime


class MessageAccepted(BaseModel):
    message: MessageOut


class GenerateIn(BaseModel):
    feedback: str | None = Field(default=None, max_length=8000)

    @field_validator("feedback")
    @classmethod
    def _feedback(cls, value: str | None) -> str | None:
        return (value or "").strip() or None


class SpecOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    version: int
    content: str
    status: Approval
    created_at: datetime


class PlanOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    version: int
    status: Approval
    plan: dict[str, Any]
    estimate: dict[str, Any]
    created_at: datetime


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    ref: str
    title: str
    milestone: str
    state: str
    attempts: int
    escalated: bool
    role: str
    size: str
    depends_on: list[str]


class TaskRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    kind: str
    attempt: int
    model: str
    state: str
    started_at: datetime
    finished_at: datetime | None
    iterations: int
    log_tail: str | None


class TaskDetailOut(TaskOut):
    runs: list[TaskRunOut]
