from __future__ import annotations

import pytest

from cobble.config import Settings
from cobble.i18n import t


def test_settings_read_cobble_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COBBLE_LITELLM_URL", "http://litellm:4000")
    monkeypatch.setenv("COBBLE_LANG", "fr")
    settings = Settings()
    assert settings.litellm_url == "http://litellm:4000"
    assert settings.lang == "fr"
    assert settings.default_model == "fake"


def test_translation_in_both_languages() -> None:
    assert t("cli.chat.reply", "en") == "Reply"
    assert t("cli.chat.reply", "fr") == "Réponse"


def test_translation_params_and_fallbacks() -> None:
    assert "503" in t("cli.chat.failed", "fr", status=503)
    assert t("cli.chat.reply", "de") == "Reply"  # unknown language -> English
    assert t("no.such.key", "en") == "no.such.key"  # unknown key -> the key


def test_empty_pack_mode_defaults_to_real(monkeypatch: pytest.MonkeyPatch) -> None:
    """Compose forwards COBBLE_PACK_MODE as an empty string when it is not set."""
    monkeypatch.setenv("COBBLE_PACK_MODE", "")
    assert Settings().pack_mode == "real"
    monkeypatch.setenv("COBBLE_PACK_MODE", "fake")
    assert Settings().pack_mode == "fake"


def test_fake_pack_is_refused_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COBBLE_PACK_MODE", "fake")
    monkeypatch.setenv("COBBLE_ENV", "production")
    with pytest.raises(ValueError):
        Settings()
