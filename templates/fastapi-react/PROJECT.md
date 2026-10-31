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

## Decisions
(none yet)

## Glossary
(none yet)
