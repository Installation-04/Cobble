.PHONY: e2e-full test-installer activation-link help install lint lint-backend lint-ui test test-backend test-ui test-integration format dev dev-down dev-logs smoke e2e bench cassettes

RUFF := cd backend && uv run --quiet ruff

help:
	@echo "Targets: install lint test test-integration format dev dev-down dev-logs smoke e2e bench cassettes"

install:
	cd backend && uv sync --locked
	cd providers/fake-llm && uv sync --locked
	cd packs/v01/agent-service && uv sync --locked
	cd packs/v01/preview-service && uv sync --locked
	cd ui && pnpm install --frozen-lockfile

lint: lint-backend lint-ui
	python3 scripts/check_i18n.py
	python3 scripts/check_no_hardcoded_colors.py

PY_DIRS := . ../scripts ../providers/fake-llm

lint-backend:
	$(RUFF) check --config pyproject.toml $(PY_DIRS)
	$(RUFF) format --config pyproject.toml --check $(PY_DIRS)
	cd backend && uv run --quiet mypy
	cd providers/fake-llm && uv run --quiet mypy
	cd packs/v01/agent-service && uv run --quiet ruff check . && uv run --quiet ruff format --check . && uv run --quiet mypy
	cd packs/v01/preview-service && uv run --quiet ruff check . && uv run --quiet ruff format --check . && uv run --quiet mypy

lint-ui:
	cd ui && pnpm run lint && pnpm run format:check && pnpm run typecheck

test: test-backend test-ui test-installer

test-backend:
	cd backend && uv run --quiet pytest -q
	cd providers/fake-llm && uv run --quiet pytest -q
	cd packs/v01/agent-service && uv run --quiet pytest -q
	cd packs/v01/preview-service && uv run --quiet pytest -q

test-ui:
	cd ui && pnpm test

test-installer:
	bash installer/tests/run.sh

format:
	$(RUFF) check --config pyproject.toml --fix $(PY_DIRS)
	$(RUFF) format --config pyproject.toml $(PY_DIRS)
	cd ui && pnpm run format

# COMPOSE_FLAGS: extra compose files, e.g. "-f my-overrides.yml" (TLS proxy CA, ports...).
COMPOSE := docker compose -f core/compose.yml $(COMPOSE_FLAGS)
HTTP_PORT = $$(sed -n 's/^COBBLE_HTTP_PORT=//p' core/.env)

dev:
	python3 scripts/dev_env.py
	$(COMPOSE) up --build -d --wait
	@echo "Cobble is up: http://localhost:$(HTTP_PORT)  (first run: make activation-link)"

dev-down:
	$(COMPOSE) down

dev-logs:
	$(COMPOSE) logs -f --tail=100

# Print a one-use link to create the admin account (valid 24 h).
activation-link:
	$(COMPOSE) exec -T api python -m cobble.cli activation-link

# Send one chat request through LiteLLM (fake provider) and show the recorded call.
smoke:
	$(COMPOSE) exec -T api python -m cobble.cli chat hello
	$(COMPOSE) exec -T postgres psql -U cobble -d cobble -c \
	  "SELECT model, prompt_tokens, completion_tokens, cost_usd FROM llm_calls ORDER BY created_at DESC LIMIT 1"

# Runs the integration tests against the core stack (published on 127.0.0.1 by an overlay).
test-integration:
	python3 scripts/dev_env.py
	$(COMPOSE) -f core/compose.test.yml up --build -d --wait
	# The planning tests drive the job queue themselves: the stack's worker must not compete.
	$(COMPOSE) -f core/compose.test.yml stop worker
	set -a; . core/.env; set +a; cd backend && \
	COBBLE_TEST_DATABASE_URL="postgresql+psycopg://cobble:$$POSTGRES_PASSWORD@127.0.0.1:55432/cobble" \
	COBBLE_TEST_REDIS_URL="redis://:$$REDIS_PASSWORD@127.0.0.1:56379/0" \
	COBBLE_TEST_LITELLM_URL="http://127.0.0.1:54000" \
	COBBLE_TEST_LITELLM_KEY="$$LITELLM_MASTER_KEY" \
	uv run --quiet pytest -q -m integration

# Re-record cassettes against a real provider (costs tokens). See providers/fake-llm/README.md.
cassettes:
	@test -n "$$FAKE_LLM_UPSTREAM_URL" -a -n "$$FAKE_LLM_UPSTREAM_API_KEY" || \
	  { echo "Set FAKE_LLM_UPSTREAM_URL and FAKE_LLM_UPSTREAM_API_KEY first." >&2; exit 2; }
	cd providers/fake-llm && FAKE_LLM_MODE=record uv run --quiet uvicorn fake_llm.app:create_app_from_env --factory --port 8999

# Not available yet: each target lands with its plan step.
# Manual, long (20+ minutes): the REAL chain (Forgejo, Woodpecker, agent-service, Aider, previews)
# replaying the to-do reference project. See docs/en/e2e-full.md. Pass options with ARGS="--keep".
e2e-full:
	bash scripts/e2e_full.sh $(ARGS)

# Browser tests (Playwright) against a FRESH stack: the spec activates the first admin account.
e2e:
	python3 scripts/dev_env.py
	$(COMPOSE) down -v
	# The browser tests run the whole build loop on in-memory fakes (no Forgejo, Docker-in-Docker...).
	COBBLE_PACK_MODE=fake COBBLE_FAKE_STEP_S=0.2 $(COMPOSE) up --build -d --wait
	port=$(HTTP_PORT); cd ui && E2E_BASE_URL=http://localhost:$$port pnpm exec playwright test

bench:
	@echo "make bench: available from v0.3 (agent benchmark)." >&2; exit 2
