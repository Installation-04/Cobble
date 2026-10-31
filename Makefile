.PHONY: help install lint lint-backend lint-ui test test-backend test-ui format dev e2e bench cassettes

RUFF := cd backend && uv run --quiet ruff

help:
	@echo "Targets: install lint test format dev e2e bench cassettes"

install:
	cd backend && uv sync --locked
	cd providers/fake-llm && uv sync --locked
	cd ui && pnpm install --frozen-lockfile

lint: lint-backend lint-ui
	python3 scripts/check_i18n.py

PY_DIRS := . ../scripts ../providers/fake-llm

lint-backend:
	$(RUFF) check --config pyproject.toml $(PY_DIRS)
	$(RUFF) format --config pyproject.toml --check $(PY_DIRS)
	cd backend && uv run --quiet mypy
	cd providers/fake-llm && uv run --quiet mypy

lint-ui:
	cd ui && pnpm run lint && pnpm run format:check && pnpm run typecheck

test: test-backend test-ui

test-backend:
	cd backend && uv run --quiet pytest -q
	cd providers/fake-llm && uv run --quiet pytest -q

test-ui:
	cd ui && pnpm test

format:
	$(RUFF) check --config pyproject.toml --fix $(PY_DIRS)
	$(RUFF) format --config pyproject.toml $(PY_DIRS)
	cd ui && pnpm run format

# Not available yet: each target lands with its plan step.
dev:
	@echo "make dev: available from step 2 (core and fake LLM provider)." >&2; exit 2
e2e:
	@echo "make e2e: available from step 3 (Playwright)." >&2; exit 2
bench:
	@echo "make bench: available from v0.3 (agent benchmark)." >&2; exit 2
cassettes:
	@echo "make cassettes: available from step 2 (fake LLM provider)." >&2; exit 2
