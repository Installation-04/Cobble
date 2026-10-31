"""Password hashing with the standard library's scrypt."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

_N = 2**14
_R = 8
_P = 1
_DKLEN = 32
_SALT_BYTES = 16
_MAXMEM = 64 * 1024 * 1024
MIN_PASSWORD_LENGTH = 10


def _derive(password: str, salt: bytes, n: int, r: int, p: int, dklen: int) -> bytes:
    return hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=n, r=r, p=p, dklen=dklen, maxmem=_MAXMEM
    )


def hash_password(password: str) -> str:
    """Return `scrypt$n$r$p$salt$hash` (salt and hash are base64)."""
    salt = secrets.token_bytes(_SALT_BYTES)
    digest = _derive(password, salt, _N, _R, _P, _DKLEN)
    b64 = base64.b64encode
    return f"scrypt${_N}${_R}${_P}${b64(salt).decode()}${b64(digest).decode()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt_b64, hash_b64 = stored.split("$")
        if scheme != "scrypt":
            return False
        expected = base64.b64decode(hash_b64)
        digest = _derive(
            password, base64.b64decode(salt_b64), int(n), int(r), int(p), len(expected)
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(digest, expected)


_DUMMY_HASH = hash_password("cobble-dummy-password")


def burn_verification() -> None:
    """Spend the cost of one verification (used when the account does not exist)."""
    verify_password("x", _DUMMY_HASH)
