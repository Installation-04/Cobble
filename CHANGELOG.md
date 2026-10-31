# Changelog

All notable changes to this project are documented here.
Format based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning follows [SemVer](https://semver.org/).

## [Unreleased]

### Added
- Repository skeleton: licenses (AGPL-3.0, Apache-2.0 for `templates/`), community files, issue and PR templates.
- Python tooling (uv, ruff, mypy strict, pytest), web tooling (pnpm, TypeScript, eslint, prettier, vitest), i18n key check, Makefile.
- GitHub Actions CI running lint and tests.
- Core stack (`core/compose.yml`): Postgres, Redis, LiteLLM, Caddy, API, worker and UI placeholder, images pinned by digest, only Caddy publishes a port. `make dev` starts it with no API key.
- Fake OpenAI-compatible LLM provider replaying cassettes (`providers/fake-llm`), with recording and automatic secret scrubbing.
- FastAPI app with `GET /api/v1/health`, Alembic with the `llm_calls` migration, Redis event bus, and a LiteLLM gateway that records tokens and cost per call.
- `make dev|dev-down|dev-logs|smoke|test-integration|cassettes`; CI job `core-stack` runs the full chain.
- i18n key check now also covers backend (`backend/cobble/locales`) messages.
