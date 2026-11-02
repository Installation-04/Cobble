"""The secrets vault: encryption bound to the module, redaction, and the encrypted store."""

from __future__ import annotations

import logging
import os
import pickle
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from cobble.db.base import Base
from cobble.db.models import Module
from cobble.module_manager.redaction import RedactingFilter, Redactor
from cobble.module_manager.secret_store import SecretStore
from cobble.module_manager.vault import (
    EncryptedSecret,
    SecretValue,
    Vault,
    VaultError,
    generate_master_key_file,
    read_master_key,
)

KEY = bytes(range(32))
KEY2 = bytes(range(32, 64))
PLAIN = "correct-horse-battery-staple-ünï"


def vault() -> Vault:
    return Vault({1: KEY})


# --- encryption -------------------------------------------------------------------------------


@pytest.mark.parametrize("plain", [PLAIN, "x", "a" * 5000, "🔑 clé secrète", "line1\nline2"])
def test_round_trip(plain: str) -> None:
    v = vault()
    encrypted = v.encrypt("forgejo", "api_token", SecretValue(plain))
    assert v.decrypt("forgejo", "api_token", encrypted).reveal() == plain


def test_the_ciphertext_hides_the_plaintext_and_the_nonce_is_fresh() -> None:
    v = vault()
    first = v.encrypt("forgejo", "api_token", SecretValue(PLAIN))
    second = v.encrypt("forgejo", "api_token", SecretValue(PLAIN))
    assert PLAIN.encode() not in first.ciphertext
    assert first.nonce != second.nonce
    assert first.ciphertext != second.ciphertext
    assert len(first.nonce) == 12
    assert first.key_version == 1


def test_a_secret_cannot_be_moved_to_another_module_or_key() -> None:
    v = vault()
    encrypted = v.encrypt("forgejo", "api_token", SecretValue(PLAIN))
    for module_id, key in [("woodpecker", "api_token"), ("forgejo", "admin_password")]:
        with pytest.raises(VaultError) as info:
            v.decrypt(module_id, key, encrypted)
        assert info.value.code == "decrypt_failed"


def test_tampering_is_detected() -> None:
    v = vault()
    encrypted = v.encrypt("forgejo", "api_token", SecretValue(PLAIN))
    flipped = bytes([encrypted.ciphertext[0] ^ 1]) + encrypted.ciphertext[1:]
    for bad in (
        EncryptedSecret(flipped, encrypted.nonce, 1),
        EncryptedSecret(encrypted.ciphertext, bytes(12), 1),
        EncryptedSecret(encrypted.ciphertext[:-1], encrypted.nonce, 1),
    ):
        with pytest.raises(VaultError) as info:
            v.decrypt("forgejo", "api_token", bad)
        assert info.value.code == "decrypt_failed"


def test_a_wrong_master_key_cannot_decrypt() -> None:
    encrypted = vault().encrypt("forgejo", "api_token", SecretValue(PLAIN))
    with pytest.raises(VaultError):
        Vault({1: KEY2}).decrypt("forgejo", "api_token", encrypted)


def test_key_versions_allow_rotation() -> None:
    old = vault().encrypt("forgejo", "api_token", SecretValue(PLAIN))
    rotated = Vault({1: KEY, 2: KEY2})
    assert rotated.current_version == 2
    assert rotated.decrypt("forgejo", "api_token", old).reveal() == PLAIN  # old data still reads
    fresh = rotated.encrypt("forgejo", "api_token", SecretValue(PLAIN))
    assert fresh.key_version == 2
    with pytest.raises(VaultError) as info:  # a version that is not loaded
        vault().decrypt("forgejo", "api_token", fresh)
    assert info.value.code == "unknown_key_version"


def test_invalid_vaults_and_empty_secrets_are_refused() -> None:
    with pytest.raises(VaultError):
        Vault({})
    with pytest.raises(VaultError):
        Vault({1: b"short"})
    with pytest.raises(VaultError) as info:
        vault().encrypt("forgejo", "api_token", SecretValue(""))
    assert info.value.code == "empty_secret"


def test_errors_never_carry_the_secret_or_the_key() -> None:
    v = vault()
    encrypted = v.encrypt("forgejo", "api_token", SecretValue(PLAIN))
    with pytest.raises(VaultError) as info:
        v.decrypt("other", "api_token", encrypted)
    rendered = f"{info.value!s} {info.value!r} {info.value.args}"
    assert PLAIN not in rendered
    assert KEY.hex() not in rendered


# --- SecretValue ------------------------------------------------------------------------------


def test_a_secret_value_never_shows_itself() -> None:
    secret = SecretValue(PLAIN)
    shown = [
        str(secret),
        repr(secret),
        f"{secret}",
        f"{secret!r}",
        "%s" % secret,  # noqa: UP031 - the old style is exactly what is being tested
        [secret].__repr__(),
    ]
    assert all(PLAIN not in s for s in shown)
    assert secret.reveal() == PLAIN
    with pytest.raises(TypeError):
        pickle.dumps(secret)


# --- master key file --------------------------------------------------------------------------


def test_generate_and_read_a_master_key(tmp_path: Path) -> None:
    path = tmp_path / "master.key"
    generate_master_key_file(path)
    assert path.stat().st_mode & 0o777 == 0o600
    key = read_master_key(path)
    assert len(key) == 32
    assert Vault.from_file(path).current_version == 1
    with pytest.raises(VaultError) as info:  # never overwrites a key (that would lose all secrets)
        generate_master_key_file(path)
    assert info.value.code == "key_file_exists"
    assert read_master_key(path) == key


def test_hex_keys_are_accepted(tmp_path: Path) -> None:
    path = tmp_path / "hex.key"
    path.write_text(KEY.hex() + "\n")
    path.chmod(0o600)
    assert read_master_key(path) == KEY


@pytest.mark.parametrize("mode", [0o644, 0o640, 0o604, 0o666])
def test_a_key_readable_by_others_is_refused(tmp_path: Path, mode: int) -> None:
    path = tmp_path / "master.key"
    path.write_bytes(KEY)
    path.chmod(mode)
    with pytest.raises(VaultError) as info:
        read_master_key(path)
    assert info.value.code == "key_file_permissions"


def test_bad_key_files_are_refused(tmp_path: Path) -> None:
    short = tmp_path / "short.key"
    short.write_bytes(b"too short")
    short.chmod(0o600)
    with pytest.raises(VaultError) as info:
        read_master_key(short)
    assert info.value.code == "bad_master_key"
    with pytest.raises(VaultError) as missing:
        read_master_key(tmp_path / "absent.key")
    assert missing.value.code == "key_file_unreadable"
    with pytest.raises(VaultError):
        read_master_key(tmp_path)  # a directory


# --- the encrypted store ----------------------------------------------------------------------


def make_session() -> Session:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = Session(engine)
    session.add_all([Module(id="forgejo", version="1"), Module(id="woodpecker", version="1")])
    session.commit()
    return session


def test_store_set_get_overwrite_and_missing() -> None:
    store = SecretStore(vault())
    with make_session() as session:
        assert store.get(session, "forgejo", "api_token") is None
        store.set(session, "forgejo", "api_token", SecretValue("first-secret-value"))
        store.set(session, "forgejo", "api_token", SecretValue("second-secret-value"))
        value = store.get(session, "forgejo", "api_token")
        assert value is not None
        assert value.reveal() == "second-secret-value"
        assert store.keys(session, "forgejo") == ["api_token"]
        assert store.keys(session, "woodpecker") == []


def test_the_database_never_holds_a_plaintext() -> None:
    store = SecretStore(vault())
    with make_session() as session:
        store.set(session, "forgejo", "api_token", SecretValue(PLAIN))
        session.commit()
        stored = session.execute(text("SELECT ciphertext, nonce FROM module_secrets")).one()
        assert PLAIN.encode() not in bytes(stored[0])
        assert PLAIN.encode() not in bytes(stored[1])


def test_generate_is_idempotent() -> None:
    store = SecretStore(vault())
    with make_session() as session:
        assert store.generate(session, "forgejo", "admin_password") is True
        first = store.get(session, "forgejo", "admin_password")
        assert store.generate(session, "forgejo", "admin_password") is False
        second = store.get(session, "forgejo", "admin_password")
        assert first is not None
        assert first == second
        assert len(first.reveal()) >= 40


def test_status_reports_set_or_unset_never_values() -> None:
    store = SecretStore(vault())
    with make_session() as session:
        store.set(session, "forgejo", "api_token", SecretValue(PLAIN))
        status = store.status(session, "forgejo", ["api_token", "admin_password"])
        assert status == {"api_token": True, "admin_password": False}
        assert PLAIN not in repr(status)


def test_delete_all_removes_only_that_module() -> None:
    store = SecretStore(vault())
    with make_session() as session:
        store.set(session, "forgejo", "api_token", SecretValue(PLAIN))
        store.set(session, "woodpecker", "agent_secret", SecretValue(PLAIN + "2"))
        store.delete_all(session, "forgejo")
        assert store.keys(session, "forgejo") == []
        assert store.keys(session, "woodpecker") == ["agent_secret"]


# --- redaction --------------------------------------------------------------------------------


def logger_with_filter(name: str, redactor: Redactor) -> tuple[logging.Logger, list[str]]:
    lines: list[str] = []

    class Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            lines.append(self.format(record))

    handler = Capture()
    handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    handler.addFilter(RedactingFilter(redactor))
    log = logging.getLogger(name)
    log.handlers = [handler]
    log.setLevel(logging.DEBUG)
    log.propagate = False
    return log, lines


def test_registered_secrets_are_masked_in_messages_arguments_and_tracebacks() -> None:
    redactor = Redactor()
    redactor.register(PLAIN)
    log, lines = logger_with_filter("test.redaction", redactor)
    log.info("token is %s", PLAIN)
    log.info(f"inline {PLAIN} here")
    try:
        raise RuntimeError(f"failed with {PLAIN}")
    except RuntimeError:
        log.exception("boom")
    assert len(lines) == 3
    assert all(PLAIN not in line for line in lines)
    assert "***" in lines[0]
    assert "RuntimeError" in lines[2]  # the traceback is kept, only the value is masked


def test_the_store_registers_the_secrets_it_touches() -> None:
    redactor = Redactor()
    store = SecretStore(vault(), redactor)
    with make_session() as session:
        store.set(session, "forgejo", "api_token", SecretValue("a-very-secret-token"))
    assert redactor.redact("use a-very-secret-token now") == "use *** now"
    fresh = Redactor()
    reading = SecretStore(vault(), fresh)
    with make_session() as session:
        store.set(session, "forgejo", "api_token", SecretValue("a-very-secret-token"))
        reading.get(session, "forgejo", "api_token")
    assert "a-very-secret-token" not in fresh.redact("x a-very-secret-token y")


def test_short_values_are_not_redacted_and_longer_ones_win() -> None:
    redactor = Redactor()
    redactor.register("abc")  # too short: it would mangle ordinary words
    assert redactor.redact("abc abc") == "abc abc"
    redactor.register("longsecret1")
    redactor.register("longsecret123")
    assert redactor.redact("x longsecret123 y") == "x *** y"


def test_the_master_key_file_is_not_world_readable_after_generation(tmp_path: Path) -> None:
    path = tmp_path / "k"
    generate_master_key_file(path)
    assert (os.stat(path).st_mode & 0o077) == 0
