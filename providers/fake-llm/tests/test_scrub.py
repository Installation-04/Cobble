from __future__ import annotations

import pytest
from fake_llm.scrub import REDACTED, scrub_text

SECRETS = [
    "sk-abcdefghijklmnopqrstuvwx",
    "sk-ant-api03-abcdefghijklmnop_qrstuv",
    "ghp_abcdefghijklmnopqrstuvwxyz0123",
    "AKIAABCDEFGHIJKLMNOP",
    "xoxb-1234567890-abcdefghij",
    "Bearer abcdefghijklmnop1234",
]


@pytest.mark.parametrize("secret", SECRETS)
def test_known_token_formats_are_removed(secret: str) -> None:
    out = scrub_text(f"use {secret} to call the api")
    assert secret not in out
    assert REDACTED in out


@pytest.mark.parametrize(
    "line",
    ['api_key = "hunter2hunter2"', "PASSWORD: correcthorsebattery", '{"token": "abc12345678"}'],
)
def test_assignments_are_removed(line: str) -> None:
    out = scrub_text(line)
    assert REDACTED in out
    assert "hunter2hunter2" not in out
    assert "correcthorsebattery" not in out
    assert "abc12345678" not in out


def test_private_key_block_is_removed() -> None:
    block = "-----BEGIN RSA PRIVATE KEY-----\nMIIabc\n-----END RSA PRIVATE KEY-----"
    assert "MIIabc" not in scrub_text(f"key:\n{block}")


def test_plain_text_is_untouched() -> None:
    assert scrub_text("Build me a todo list app") == "Build me a todo list app"
