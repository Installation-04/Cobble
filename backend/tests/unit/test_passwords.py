from __future__ import annotations

from cobble.auth.passwords import hash_password, verify_password
from cobble.auth.tokens import hash_token, new_token


def test_hash_verifies_and_is_salted() -> None:
    first, second = hash_password("correct horse"), hash_password("correct horse")
    assert first != second
    assert first.startswith("scrypt$")
    assert verify_password("correct horse", first)
    assert not verify_password("wrong horse", first)


def test_verify_rejects_malformed_hashes() -> None:
    for stored in ("", "plain", "bcrypt$1$2$3$a$b", "scrypt$x$8$1$AA==$AA=="):
        assert not verify_password("anything", stored)


def test_unicode_password() -> None:
    stored = hash_password("mot de passe é€✓")
    assert verify_password("mot de passe é€✓", stored)


def test_tokens_are_random_and_hash_is_sha256_hex() -> None:
    assert new_token() != new_token()
    digest = hash_token("abc")
    assert len(digest) == 64
    assert digest == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
