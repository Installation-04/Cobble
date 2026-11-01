"""Model connections: language-model services the administrator connected with an API key.

The key is encrypted by the vault (bound to the connection's name) and never leaves the
module-manager except inside the gateway's own include file. The default model is the platform's
choice among them (or the configured one). All methods take a session and only flush: the caller
commits once the gateway has accepted the new list, so a refused change leaves nothing behind.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from cobble.db.models import LlmConnection, PlatformState

from .llm import LlmEntry
from .redaction import Redactor
from .vault import EncryptedSecret, SecretValue, Vault

NAMESPACE = "llm"  # the vault binds a secret to (namespace, name)
NAME = re.compile(r"^[a-z0-9][a-z0-9._-]{0,39}$")
MODEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,99}$")
RESERVED = {"fake", "default"}
# provider -> the gateway's provider prefix. `custom` is any OpenAI-compatible service.
PROVIDERS: dict[str, str] = {
    "openai": "openai",
    "anthropic": "anthropic",
    "openrouter": "openrouter",
    "custom": "openai",
}


class ConnectionInvalid(ValueError):
    """The request is not acceptable; `fields` names what to fix."""

    def __init__(self, fields: list[str]) -> None:
        super().__init__(", ".join(fields))
        self.fields = fields


class ConnectionUnknown(LookupError):
    def __init__(self, name: str) -> None:
        super().__init__(name)
        self.name = name


@dataclass(frozen=True)
class ConnectionInfo:
    """What is shown about a connection: never its key."""

    name: str
    provider: str
    model: str
    base_url: str | None
    default: bool


def _valid_url(value: str) -> bool:
    try:
        parts = urlsplit(value)
    except ValueError:
        return False
    return (
        parts.scheme in ("http", "https")
        and bool(parts.hostname)
        and not parts.username
        and not parts.password
        and not parts.query
        and not parts.fragment
        and len(value) <= 300
    )


def validate(name: str, provider: str, model: str, api_key: str, base_url: str | None) -> list[str]:
    """The fields that are wrong (empty when the request is fine)."""
    bad: list[str] = []
    if not NAME.match(name) or name in RESERVED:
        bad.append("name")
    if provider not in PROVIDERS:
        bad.append("provider")
    if not MODEL.match(model):
        bad.append("model")
    key = api_key.strip()
    if not key or len(key) > 500 or any(c.isspace() or ord(c) < 32 for c in key):
        bad.append("api_key")
    if provider == "custom":
        if not base_url or not _valid_url(base_url):
            bad.append("base_url")
    elif base_url:  # a key must not be sent to an address chosen under another service's name
        bad.append("base_url")
    return bad


class ConnectionStore:
    def __init__(self, vault: Vault, redactor: Redactor | None = None) -> None:
        self._vault = vault
        self._redactor = redactor

    # --- the default ---------------------------------------------------------------------------

    @staticmethod
    def _state(session: Session) -> PlatformState:
        state = session.get(PlatformState, 1)
        if state is None:
            state = PlatformState(id=1)
            session.add(state)
            session.flush()
        return state

    def default(self, session: Session) -> str | None:
        state = session.get(PlatformState, 1)
        return state.default_model if state is not None else None

    def set_default(self, session: Session, name: str | None) -> None:
        if name is not None and session.get(LlmConnection, name) is None:
            raise ConnectionUnknown(name)
        self._state(session).default_model = name
        session.flush()

    # --- the connections -----------------------------------------------------------------------

    def describe(self, session: Session) -> list[ConnectionInfo]:
        default = self.default(session)
        rows = session.scalars(select(LlmConnection).order_by(LlmConnection.name))
        return [
            ConnectionInfo(r.name, r.provider, r.model, r.base_url, r.name == default) for r in rows
        ]

    def put(
        self,
        session: Session,
        name: str,
        provider: str,
        model: str,
        api_key: SecretValue,
        base_url: str | None = None,
    ) -> None:
        bad = validate(name, provider, model, api_key.reveal(), base_url)
        if bad:
            raise ConnectionInvalid(bad)
        key = SecretValue(api_key.reveal().strip())
        if self._redactor is not None:
            self._redactor.register(key.reveal())
        encrypted = self._vault.encrypt(NAMESPACE, name, key)
        row = session.get(LlmConnection, name)
        if row is None:
            row = LlmConnection(name=name)
            session.add(row)
        row.provider = provider
        row.model = model
        row.base_url = base_url or None
        row.ciphertext = encrypted.ciphertext
        row.nonce = encrypted.nonce
        row.key_version = encrypted.key_version
        session.flush()

    def remove(self, session: Session, name: str) -> None:
        row = session.get(LlmConnection, name)
        if row is None:
            raise ConnectionUnknown(name)
        if self.default(session) == name:
            self._state(session).default_model = None  # back to the configured default
        session.delete(row)
        session.flush()

    # --- for the gateway -----------------------------------------------------------------------

    def entries(self, session: Session) -> list[LlmEntry]:
        """One gateway entry per connection, with its decrypted key."""
        entries: list[LlmEntry] = []
        for row in session.scalars(select(LlmConnection).order_by(LlmConnection.name)):
            secret = self._vault.decrypt(
                NAMESPACE, row.name, EncryptedSecret(row.ciphertext, row.nonce, row.key_version)
            )
            if self._redactor is not None:
                self._redactor.register(secret.reveal())
            entries.append(
                LlmEntry(
                    name=row.name,
                    model=f"{PROVIDERS[row.provider]}/{row.model}",
                    api_base=row.base_url,
                    api_key=secret.reveal(),
                    local=False,
                )
            )
        return entries
