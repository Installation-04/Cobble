"""Errors raised by the pack providers. Messages never contain credentials."""

from __future__ import annotations


class ProviderError(Exception):
    """A pack service answered with an error or could not be reached."""

    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class ProviderUnavailable(ProviderError):
    """The service is unreachable (network error, timeout)."""


class ProviderAuthError(ProviderError):
    """The token is missing, expired or lacks a scope (HTTP 401/403)."""


class ProviderNotFound(ProviderError):
    """The repository, pull request or pipeline does not exist (HTTP 404)."""


class ProviderConflict(ProviderError):
    """The resource already exists or the state forbids the change (HTTP 409/422)."""
