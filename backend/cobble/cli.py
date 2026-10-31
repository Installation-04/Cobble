"""Developer CLI: `python -m cobble.cli chat "hello"`."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from redis import Redis

from cobble.config import get_settings
from cobble.db import make_engine, make_session_factory
from cobble.i18n import t
from cobble.router.gateway import GatewayError, LiteLLMGateway


def main(argv: Sequence[str] | None = None) -> int:
    settings = get_settings()
    parser = argparse.ArgumentParser(prog="cobble")
    sub = parser.add_subparsers(dest="command", required=True)
    chat = sub.add_parser("chat")
    chat.add_argument("message")
    chat.add_argument("--model", default=settings.default_model)
    args = parser.parse_args(argv)

    gateway = LiteLLMGateway(
        settings.litellm_url,
        settings.litellm_key,
        make_session_factory(make_engine(settings.database_url)),
        events=Redis.from_url(settings.redis_url),
    )
    try:
        result = gateway.chat(args.model, [{"role": "user", "content": args.message}])
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
