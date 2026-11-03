"""Developer CLI: `python -m cobble.cli chat "hello"`."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from redis import Redis
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, sessionmaker

from cobble import cli_models, cli_modules
from cobble.auth.activation import ACTIVATION_LIFETIME, create_activation_token
from cobble.config import Settings, get_settings
from cobble.db import AuthSession, User, make_engine, make_session_factory
from cobble.i18n import t
from cobble.router.gateway import GatewayError, LiteLLMGateway
from cobble.router.policy import ModelPolicy


def _session_factory(settings: Settings) -> sessionmaker[Session]:
    return make_session_factory(make_engine(settings.database_url))


def _activation_link(settings: Settings) -> int:
    lang = settings.lang
    with _session_factory(settings)() as db:
        if db.scalar(select(func.count()).select_from(User)):
            print(t("cli.activation.already_initialized", lang), file=sys.stderr)
            return 1
        token, expires_at = create_activation_token(db)
    base = settings.public_url.rstrip("/")
    print(f"{t('cli.activation.link', lang)}: {base}/activate?token={token}")
    print(
        t(
            "cli.activation.expires",
            lang,
            expires=expires_at.strftime("%Y-%m-%d %H:%M UTC"),
            hours=int(ACTIVATION_LIFETIME.total_seconds() // 3600),
        )
    )
    return 0


def _reset_admin(settings: Settings) -> int:
    """Invalidate the admin's sessions and print a link to set a new email and password.

    The admin's projects and data are kept.
    """
    lang = settings.lang
    with _session_factory(settings)() as db:
        user = db.scalars(select(User).order_by(User.created_at)).first()
        if user is None:
            print(t("cli.reset.no_admin", lang), file=sys.stderr)
            return 1
        db.execute(delete(AuthSession).where(AuthSession.user_id == user.id))
        db.commit()
        token, expires_at = create_activation_token(db, user_id=user.id)
    base = settings.public_url.rstrip("/")
    print(t("cli.reset.done", lang))
    print(f"{t('cli.activation.link', lang)}: {base}/activate?token={token}")
    print(
        t(
            "cli.activation.expires",
            lang,
            expires=expires_at.strftime("%Y-%m-%d %H:%M UTC"),
            hours=int(ACTIVATION_LIFETIME.total_seconds() // 3600),
        )
    )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    settings = get_settings()
    parser = argparse.ArgumentParser(prog="cobble")
    sub = parser.add_subparsers(dest="command", required=True)
    chat = sub.add_parser("chat")
    chat.add_argument("message")
    chat.add_argument("--model", default=None, help="a model name (default: the platform default)")
    sub.add_parser("activation-link")
    sub.add_parser("reset-admin")
    cli_modules.add_parser(sub)
    cli_models.add_parser(sub)
    args = parser.parse_args(argv)

    if args.command == "activation-link":
        return _activation_link(settings)
    if args.command == "reset-admin":
        return _reset_admin(settings)
    if args.command == "modules":
        return cli_modules.run(args, settings)
    if args.command == "models":
        return cli_models.run(args, settings)

    gateway = LiteLLMGateway(
        settings.litellm_url,
        settings.litellm_key,
        _session_factory(settings),
        events=Redis.from_url(settings.redis_url),
    )
    try:
        model = args.model or ModelPolicy(_session_factory(settings), settings).default()
        result = gateway.chat(model, [{"role": "user", "content": args.message}])
    except GatewayError as exc:
        print(t("cli.chat.failed", settings.lang, status=exc.status), file=sys.stderr)
        return 1
    lang = settings.lang
    print(f"{t('cli.chat.reply', lang)}: {result.content}")
    print(f"{t('cli.chat.model', lang)}: {result.model}")
    print(f"{t('cli.chat.tokens', lang)}: {result.prompt_tokens} / {result.completion_tokens}")
    print(f"{t('cli.chat.cost', lang)}: {result.cost_usd}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
