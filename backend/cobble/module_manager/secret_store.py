"""Encrypted secrets of the modules, in the database (`module_secrets`)."""

from __future__ import annotations

import secrets
from collections.abc import Sequence

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from cobble.db.models import ModuleSecret

from .redaction import Redactor
from .vault import EncryptedSecret, SecretValue, Vault


class SecretStore:
    def __init__(self, vault: Vault, redactor: Redactor | None = None) -> None:
        self._vault = vault
        self._redactor = redactor

    def set(self, session: Session, module_id: str, key: str, value: SecretValue) -> None:
        encrypted = self._vault.encrypt(module_id, key, value)
        if self._redactor is not None:
            self._redactor.register(value.reveal())
        row = session.get(ModuleSecret, (module_id, key))
        if row is None:
            session.add(
                ModuleSecret(
                    module_id=module_id,
                    key=key,
                    ciphertext=encrypted.ciphertext,
                    nonce=encrypted.nonce,
                    key_version=encrypted.key_version,
                )
            )
        else:
            row.ciphertext = encrypted.ciphertext
            row.nonce = encrypted.nonce
            row.key_version = encrypted.key_version
        session.flush()

    def get(self, session: Session, module_id: str, key: str) -> SecretValue | None:
        row = session.get(ModuleSecret, (module_id, key))
        if row is None:
            return None
        value = self._vault.decrypt(
            module_id, key, EncryptedSecret(row.ciphertext, row.nonce, row.key_version)
        )
        if self._redactor is not None:
            self._redactor.register(value.reveal())
        return value

    def generate(self, session: Session, module_id: str, key: str) -> bool:
        """Create a random secret unless one exists (idempotent). Returns True when created."""
        if session.get(ModuleSecret, (module_id, key)) is not None:
            return False
        self.set(session, module_id, key, SecretValue(secrets.token_urlsafe(32)))
        return True

    def keys(self, session: Session, module_id: str) -> list[str]:
        """The names (never the values) of the secrets stored for a module."""
        return sorted(
            session.scalars(select(ModuleSecret.key).where(ModuleSecret.module_id == module_id))
        )

    def status(self, session: Session, module_id: str, declared: Sequence[str]) -> dict[str, bool]:
        """For the API: which declared secrets are set. Values are never exposed."""
        stored = set(self.keys(session, module_id))
        return {key: key in stored for key in declared}

    def delete_all(self, session: Session, module_id: str) -> None:
        session.execute(delete(ModuleSecret).where(ModuleSecret.module_id == module_id))
