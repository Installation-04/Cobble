"""The secrets vault: AES-256-GCM, bound to the module and the key name.

Rules (CLAUDE.md rule 8, PLAN.md section 7):
- the master key is a file readable by its owner only, mounted in the module-manager alone;
- a ciphertext is bound to `module_id:key` (authenticated data): moving it to another module or
  key makes it undecryptable;
- plaintexts travel as `SecretValue`, whose `str()`/`repr()` never show the value;
- errors carry a short code, never a plaintext, a ciphertext or key material.
"""

from __future__ import annotations

import os
import stat
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

KEY_BYTES = 32
NONCE_BYTES = 12


class VaultError(Exception):
    """A vault failure. `code` is stable and safe to log or show; nothing secret is added."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class SecretValue:
    """A secret in memory. Printing, formatting or logging it shows `***`; use `reveal()`."""

    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        self._value = value

    def reveal(self) -> str:
        return self._value

    def __repr__(self) -> str:
        return "SecretValue(***)"

    def __str__(self) -> str:
        return "***"

    def __format__(self, spec: str) -> str:
        return "***"

    def __eq__(self, other: object) -> bool:
        return isinstance(other, SecretValue) and self._value == other._value

    def __hash__(self) -> int:
        return hash(self._value)

    def __reduce__(self) -> tuple[type[SecretValue], tuple[str]]:
        raise TypeError("a SecretValue cannot be pickled")


@dataclass(frozen=True)
class EncryptedSecret:
    ciphertext: bytes
    nonce: bytes
    key_version: int


def _aad(module_id: str, key: str) -> bytes:
    return f"{module_id}:{key}".encode()


class Vault:
    """Encrypts and decrypts secrets with versioned master keys (the highest is current)."""

    def __init__(self, keys: Mapping[int, bytes]) -> None:
        if not keys:
            raise VaultError("no_master_key")
        for version, key in keys.items():
            if version < 1 or len(key) != KEY_BYTES:
                raise VaultError("bad_master_key")
        self._ciphers = {version: AESGCM(key) for version, key in keys.items()}
        self.current_version = max(keys)

    @classmethod
    def from_file(cls, path: Path | str) -> Vault:
        """Load a single master key (version 1) from a file: 32 raw bytes or 64 hex digits."""
        return cls({1: read_master_key(path)})

    def encrypt(self, module_id: str, key: str, value: SecretValue) -> EncryptedSecret:
        plaintext = value.reveal()
        if not plaintext:
            raise VaultError("empty_secret")
        nonce = os.urandom(NONCE_BYTES)
        ciphertext = self._ciphers[self.current_version].encrypt(
            nonce, plaintext.encode(), _aad(module_id, key)
        )
        return EncryptedSecret(ciphertext, nonce, self.current_version)

    def decrypt(self, module_id: str, key: str, secret: EncryptedSecret) -> SecretValue:
        cipher = self._ciphers.get(secret.key_version)
        if cipher is None:
            raise VaultError("unknown_key_version")
        try:
            plaintext = cipher.decrypt(secret.nonce, secret.ciphertext, _aad(module_id, key))
        except (InvalidTag, ValueError):
            raise VaultError("decrypt_failed") from None
        return SecretValue(plaintext.decode())


def read_master_key(path: Path | str) -> bytes:
    """Read a master key file, refusing one that other users could read."""
    target = Path(path)
    try:
        info = target.stat()
    except OSError:
        raise VaultError("key_file_unreadable") from None
    if not stat.S_ISREG(info.st_mode):
        raise VaultError("key_file_unreadable")
    if info.st_mode & 0o077:
        raise VaultError("key_file_permissions")
    try:
        raw = target.read_bytes()
    except OSError:
        raise VaultError("key_file_unreadable") from None
    if len(raw) == KEY_BYTES:
        return raw
    try:
        decoded = bytes.fromhex(raw.decode().strip())
    except (UnicodeDecodeError, ValueError):
        raise VaultError("bad_master_key") from None
    if len(decoded) != KEY_BYTES:
        raise VaultError("bad_master_key")
    return decoded


def generate_master_key_file(path: Path | str) -> None:
    """Create a new master key file (mode 0600). Never overwrites an existing key."""
    target = Path(path)
    try:
        descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise VaultError("key_file_exists") from None
    except OSError:
        raise VaultError("key_file_unreadable") from None
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(os.urandom(KEY_BYTES))
