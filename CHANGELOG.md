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
- Authentication: single admin created from a one-use activation link (`make activation-link`), scrypt passwords, hashed opaque sessions in an HttpOnly cookie, CSRF header, login rate limit. Folders and projects API (ADR 0003).
- React UI shell in the Open WebUI style: sidebar with project folders, top bar, chat area placeholder, settings dialog, System/Light/Dark theme from CSS tokens, FR/EN switch without reload. Lint rules reject literal UI strings and hard-coded colors; WCAG AA contrast of the tokens is tested.
- Capability interfaces (`LLMClient`, `GitProvider`, `CIProvider`, `AgentRunner`) with in-memory fakes, and a cost router that maps roles (`planner`, `test-writer`, `worker`, `reviewer`) to models and enforces a hard per-project budget: the project is paused and `budget.reached` is published at the cap (`budget.warning` at 80 %). Projects expose `budget_usd` and `status`.
- `python -m cobble.cli reset-admin`: new one-use link to set a new email and password without losing projects.
- Interview, spec and plan: per-project chat with the `planner` role (answers in the user's language), spec generation and approval, plan generation validated against a strict schema (every task has acceptance criteria and a size S or M; dependencies are acyclic), cost estimate shown before approval. Work runs in the worker; progress is pushed to the browser over server-sent events. Reference project `reference-projects/todo` and cassettes replay the whole flow.
- Installer (`installer/install.sh`) and `cobble` CLI (`status`, `logs`, `update`, `uninstall`, `doctor`, `reset-admin`), idempotent, FR/EN, with a CI matrix on Ubuntu 24.04/26.04 and Debian 12/13.
- `make e2e` (Playwright) against the full stack; CI job `e2e`.
- i18n key check now also covers backend (`backend/cobble/locales`) messages.
