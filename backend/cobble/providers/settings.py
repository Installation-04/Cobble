"""Settings of the v0.1 pack, read from COBBLE_PACK_* variables.

`hooks/register-core.sh` writes them to `packs/v01/.env.pack` (outside git); mount or load that
file in the api and worker services.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class PackSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="COBBLE_PACK_", extra="ignore")

    # In-network URLs (the pack services are reachable on the shared `cobble_core` network).
    forgejo_url: str = "http://forgejo:3000"
    forgejo_token: SecretStr = SecretStr("")
    # Account that owns the generated repositories. Empty: the token's own user.
    forgejo_owner: str = ""
    woodpecker_url: str = "http://woodpecker-server:8000/ci"
    woodpecker_token: SecretStr = SecretStr("")

    default_branch: str = "main"
    # squash | merge | rebase | rebase-merge
    merge_style: str = "squash"
    # Forgejo status-check pattern that must be green on the default branch.
    required_check: str = "ci/woodpecker/pr/*"
    git_author_name: str = "Cobble"
    git_author_email: str = "cobble@cobble.invalid"

    http_timeout_s: float = 30.0
    git_timeout_s: float = 120.0
    ci_poll_interval_s: float = 5.0

    def configured(self) -> bool:
        return bool(
            self.forgejo_token.get_secret_value() and self.woodpecker_token.get_secret_value()
        )


def load_settings(env_file: Path | None = None) -> PackSettings:
    """Settings from the environment, optionally completed by a `.env.pack` file."""
    if env_file is not None and env_file.exists():
        return PackSettings(_env_file=env_file)  # type: ignore[call-arg]
    return PackSettings()
