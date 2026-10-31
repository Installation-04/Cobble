# 0001 — Repository tooling

Status: accepted (v0.1, step 1)

- **README**: a single bilingual file (FR then EN) rather than two files, to keep them in sync.
- **Python**: uv project in `backend/` (lockfile `backend/uv.lock`); ruff for lint and format; mypy strict on `cobble/`.
- **Web**: pnpm project in `ui/`, no workspace at the root; React/Vite/Tailwind arrive in step 3.
- **i18n check**: `scripts/check_i18n.py`, Python stdlib only, so it runs without installing the web stack.
- **Placeholder targets**: `make dev|e2e|bench|cassettes` exist from the start and fail with a clear message until their step lands.
