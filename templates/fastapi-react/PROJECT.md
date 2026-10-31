# {{project_name}}: project memory

Read by every agent before working; updated by the planner. Keep it short and factual.

## Stack
- Backend: Python 3.12, FastAPI, tests with pytest, lint and format with ruff (uv for dependencies).
- Frontend: React, Vite, TypeScript, tests with vitest (pnpm).
- CI: Woodpecker (`.woodpecker.yaml`): lint, backend tests, frontend tests, Semgrep, Trivy, Gitleaks.

## Conventions
- One small change per branch; open a merge request; merge only when CI is green.
- Tests first: a test describes the acceptance criterion before the implementation.
- No secrets in the code: use environment variables with dummy values for local runs.
- Keep `uv.lock` and `frontend/pnpm-lock.yaml` committed.

## Demo
- Each milestone is deployed as a demo: `docker build` of the `Dockerfile` (frontend built with Vite, served by FastAPI under `/`, API under `/api`), run as a non-root user on a read-only filesystem. It is reached at `/demo/<project>/<milestone>/`, so:
  - use RELATIVE URLs in the frontend (`fetch("api/todos")`, never `fetch("/api/todos")`; no absolute asset paths; if you add routing, use a hash router or a relative basename);
  - write files (SQLite, uploads) only under `COBBLE_DATA_DIR` (default `/tmp` in the demo);
  - `app/seed.py` `seed()` fills an empty database with realistic demo data at the first start. Keep it idempotent, offline and free of secrets.
- The API stays under `/api` (see `app/main.py`); `app/serve.py` only mounts the built frontend and runs the seed.

## Decisions
(none yet)

## Glossary
(none yet)
