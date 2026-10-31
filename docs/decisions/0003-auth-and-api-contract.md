# 0003 — Authentication, sessions and the step-3 API contract

Status: accepted (v0.1, step 3)

## Decisions
- **Single admin, activation link.** The first admin is created from a one-use activation link (`python -m cobble.cli activation-link` prints `{COBBLE_PUBLIC_URL}/activate?token=…`). Only the SHA-256 of the token is stored; it expires after 24 h and is consumed on use. Once a user exists, `activate` answers 409.
- **Passwords**: `hashlib.scrypt` from the standard library (no new dependency), per-password random salt, constant-time compare. Minimum length 10.
- **Sessions**: opaque random token in cookie `cobble_session` (HttpOnly, SameSite=Lax, Path=/, `Secure` when `COBBLE_COOKIE_SECURE=1`). Only its SHA-256 is stored. Lifetime 7 days, extended on use. Logout deletes the row.
- **CSRF**: every unsafe method (POST/PATCH/PUT/DELETE) must carry `X-Requested-With: cobble`. Browsers cannot add that header cross-site without a CORS preflight, and no CORS is allowed. Missing header → 403 `csrf_failed`.
- **Brute force**: 5 failed logins per email+IP in 15 minutes (Redis counter) → 429 `too_many_attempts`.
- **API messages are codes, not text.** Errors are `{"error": {"code": "<snake_case>", "params": {...}}}` and the UI translates `errors.<code>` (fr + en). FastAPI validation errors are mapped to `422 {"error": {"code": "validation_error", "params": {"fields": ["email", …]}}}`.

## Endpoints (all under `/api/v1`, JSON, ids are UUID strings)
| Method + path | Body | Success | Errors |
|---|---|---|---|
| `GET /setup/status` | — | `200 {"initialized": bool}` | |
| `POST /auth/activate` | `{token, email, password, lang?}` | `201 {user}` + cookie | `400 activation_invalid`, `410 activation_expired`, `409 already_initialized` |
| `POST /auth/login` | `{email, password}` | `200 {user}` + cookie | `401 invalid_credentials`, `429 too_many_attempts` |
| `POST /auth/logout` | — | `204` | |
| `GET /auth/me` | — | `200 {user}` | `401 unauthenticated` |
| `PATCH /auth/me` | `{lang?: "fr"\|"en", theme?: "system"\|"light"\|"dark"}` | `200 {user}` | `401` |
| `GET /folders` | — | `200 [{id, name, position}]` | `401` |
| `POST /folders` | `{name}` (1–100 chars) | `201 {id, name, position}` | `401`, `422` |
| `PATCH /folders/{id}` | `{name?}` | `200 {…}` | `404 not_found` |
| `DELETE /folders/{id}` | — | `204`; its projects become unfiled (`folder_id` null) | `404` |
| `GET /projects` | — | `200 [{id, name, folder_id, created_at}]` | `401` |
| `POST /projects` | `{name, folder_id?}` | `201 {…}` | `404 not_found` (unknown folder), `422` |
| `PATCH /projects/{id}` | `{name?, folder_id?}` (`folder_id: null` unfiles) | `200 {…}` | `404` |
| `DELETE /projects/{id}` | — | `204` | `404` |

`user` = `{id, email, role: "admin", lang: "fr"|"en", theme: "system"|"light"|"dark"}`. New users default to `lang` from the activation body (else `en`) and `theme: "system"`.

## UI
React + Vite + TypeScript, Tailwind, Radix primitives (shadcn style), react-i18next, react-router. All colors come from CSS variable tokens (`:root` and `.dark`); no color literal outside the token file (enforced by `scripts/check_no_hardcoded_colors.py`). No literal user-visible string in JSX (enforced by eslint `react/jsx-no-literals`). Routes: `/activate`, `/login`, `/` (shell), `/projects/:id`. The UI talks to `/api/v1` on the same origin (Caddy), never to another host.
