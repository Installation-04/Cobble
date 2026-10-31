# Changelog

All notable changes to this project are documented here.
Format based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning follows [SemVer](https://semver.org/).

## [Unreleased]

### Fixed
- Full real chain run end to end with the fake LLM (`make e2e-full`, PASS): `gen-env.sh` no longer fails on a first run; the backend image ships `git`; the runner image pre-warms a uv cache and a pnpm store with the template's dependencies and no longer leaks Aider's uv environment into project test runs; frontend tasks install dependencies before testing; a merge refused while Forgejo recomputes mergeability is retried. The harness takes `E2E_HOST` and `E2E_BUILD_CA`.

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
- Fixed pack (`packs/v01`): Forgejo and Woodpecker wired automatically, `ForgejoGit` and `WoodpeckerCI` providers, project template `templates/fastapi-react` with lint, tests, Semgrep, Trivy and Gitleaks; merge refused unless CI is green.
- Agent runner (Aider in a locked-down container, one per task) and `agent-service`, an egress allowlist proxy, and an internal LLM endpoint with signed per-run tokens so agent calls go through the cost router.
- Scheduler: tests-first runs (test-writer then worker), parallel only for independent tasks with disjoint files, loop detection, escalation, resume after a worker restart.
- Milestone demos: build, tag and preview per milestone, validate, comment (becomes a task) or revert to the previous milestone. Preview service for real previews; fake pack mode for development and CI.
- Agents tab (live logs, diff, pause/resume/stop/retry), Demo tab and Costs tab (USD and tokens by task, model and role).
- Public documentation is English-first (README, wiki, release notes, CONTRIBUTING, SECURITY) with a French version below each; wiki pages renamed in English.
- README with screenshots (`make screenshots` regenerates them), bilingual wiki sources in `docs/wiki` and `scripts/publish_wiki.sh`.
- `make e2e` (Playwright) against the full stack; CI job `e2e`.
- i18n key check now also covers backend (`backend/cobble/locales`) messages.
