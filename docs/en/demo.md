# Milestone demos

At the end of each milestone of the plan Cobble builds a demo of the app, you try it, and you
either validate it, comment on it, or go back. This page explains the flow, the pieces and the
security of the previews. The contract is ADR 0007 (`docs/decisions/0007-demo-agents-costs.md`).

## The flow

1. Every milestone gets a synthetic task `DEMO-M1`, `DEMO-M2`... It depends on all the tasks of
   its milestone and rewrites `app/seed.py` so the demo opens on realistic data (plausible names,
   dates and quantities; never an empty screen). There is no test-writer step for it; the whole
   existing test suite must stay green.
2. When the `DEMO-Mx` task is merged the milestone is **built**: Cobble tags the default branch
   (`milestone-M1`; later builds of the same milestone are `milestone-M1-r2`, `-r3`...), asks the
   preview service to deploy that tag, and stores the demo address `/demo/<project>/<milestone>/`.
   The event `milestone.updated {ref, status, preview_state}` tells the UI.
3. You **validate** the milestone (`POST .../milestones/M1/validate`). When every milestone is
   validated the project is **done**; until then it stays `building`.
4. You can **comment** (`POST .../comments`, 1 to 2000 characters). The comment becomes a task
   `C-001`, `C-002`... on that milestone, written tests-first like any task. The milestone goes back
   to `pending` and a `done` project goes back to `building`. When the comment is merged the
   milestone is built again (new tag, new demo).
5. You can **revert** (`POST .../revert`, answered `202`, run by the worker). Cobble restores the
   tag of the previous milestone (the template's first commit for `M1`) through a merge request
   like any other change, so CI and the branch protection still apply. The milestone and the later
   ones go back to `pending` and their tasks are reset to `todo`; they wait for the restore
   (`R-001`...) to be merged.

Errors are codes only: `404 not_found`, `409 wrong_state` (validate needs `built`; comment and
revert need `built` or `validated`; a revert of `M2` also needs `M1` built or validated),
`422 validation_error`, `503 queue_unavailable`.

Without a preview service (no `COBBLE_PREVIEW_SERVICE_TOKEN`) the demo flow is off and a project is
`done` as soon as every task is merged, as before.

## Pieces

| Piece | Role |
|---|---|
| `scheduler/demo.py` | milestone rules: validate, comment, revert, project completion |
| `capabilities/preview.py` | `PreviewProvider` (`deploy`, `status`, `remove`) |
| `providers/preview_service.py` | HTTP client of the preview service |
| `packs/v01/preview-service/` | builds the tag, runs it, proxies `/demo/...`, stops idle demos |
| `packs/v01/compose.preview.yml` | the service, its internal network `cobble_previews` |
| `packs/v01/preview-service/demo.caddy` | Caddy route to copy into `packs/v01/caddy/` |
| `templates/fastapi-react/Dockerfile` | image of the generated app |

### Settings

Core (`api`, `worker`): `COBBLE_PREVIEW_SERVICE_URL` (default `http://preview-service:8091`) and
`COBBLE_PREVIEW_SERVICE_TOKEN`. Preview service: `COBBLE_PREVIEW_SERVICE_TOKEN`,
`COBBLE_PACK_FORGEJO_URL|TOKEN|OWNER` (same values as agent-service), `COBBLE_PREVIEW_NETWORK`
(`cobble_previews`), `COBBLE_PREVIEW_MEMORY_MB` (512), `COBBLE_PREVIEW_CPUS` (1),
`COBBLE_PREVIEW_PIDS` (256), `COBBLE_PREVIEW_IDLE_TTL_S` (1800), `COBBLE_PREVIEW_MAX_RUNNING` (6),
`COBBLE_PREVIEW_BUILD_ARGS` (JSON object of Docker build arguments, for example proxy settings),
`COBBLE_PREVIEW_SANDBOX` (1). `preview-service/gen-env.sh` writes `.env.preview` and
`.env.preview.core` (mode 600).

### Caddy

`/demo/*` must reach the preview service. The snippet is `packs/v01/preview-service/demo.caddy`:
copy it to `packs/v01/caddy/demo.caddy` when the real service runs. Everything in that directory
is imported by the core Caddy ahead of its own routes, so the copy takes precedence. Without the
copy `/demo/*` goes to the API, which only answers it in the fake pack mode.

## Security of the previews

- The demo is code written by an agent. It runs in its own container: non-root user (10001, whatever
  the Dockerfile says), read-only root filesystem (a 64 MB tmpfs on `/tmp`), all capabilities dropped,
  `no-new-privileges`, memory, CPU and PID limits, no published port, no Docker socket, no secret in its
  environment. It lives on the `cobble_previews` network, which is `internal`: no route to the internet,
  the host or the rest of Cobble. Only the preview service can reach it.
- The preview service is the second (with agent-service) component that holds the Docker socket. It
  never runs generated code itself; `docker build` runs the generated Dockerfile in the daemon, with
  network access for the package managers. Treat a repository's Dockerfile as code that CI vetted,
  not as trusted.
- The repository token reaches `git` only through `GIT_ASKPASS`; `.git` is never part of the build
  context; the credentials never appear in an error returned to the core.
- `/demo/...` is public (no Cobble login): the project id in the address is the secret. Cookies and
  `Authorization` headers are never forwarded to the demo, and the demo's `Set-Cookie` is dropped.
- The demo is served from the same host as Cobble, so by default each response carries
  `Content-Security-Policy: sandbox allow-scripts allow-forms ...` (no `allow-same-origin`): the page
  gets an opaque origin and cannot read Cobble's cookies or call its API as you. The proxy answers CORS
  itself so the demo can still call its own API. The cost: `localStorage` and cookies are unavailable
  to the demo. `COBBLE_PREVIEW_SANDBOX=0` removes this (only for a single-user, trusted instance).
- Idle demos stop after `COBBLE_PREVIEW_IDLE_TTL_S` seconds (the image is kept) and wake up on the
  next request; at most `COBBLE_PREVIEW_MAX_RUNNING` run at once (the least recently used stops).

Limits of v0.1: the tag is placed on the head of the default branch when the `DEMO` task has been
merged and noticed (a later milestone's merge in between would be included); a redeploy that fails to
build replaces the working demo with an error page; one build runs at a time.

## Fake pack mode (development and tests only)

`COBBLE_PACK_MODE=fake` replaces git, CI, the agent runner and the preview service with in-memory
fakes: a started project plays the whole loop in seconds without Docker, a git server or a model, and
the API serves a small to-do demo page at `/demo/<project>/<milestone>/` itself (the comments you
made appear on it). Settings: `COBBLE_FAKE_STEP_S` (0.3, duration of one simulated agent step) and
`COBBLE_SCHEDULER_INTERVAL_S` (0.5 in fake mode unless you set it). The fakes keep no state, so the
`api` and `worker` containers agree on logs and diffs. `GET /api/v1/health` reports `pack_mode`.

**Never use it for real projects**: nothing is built, tested or reviewed. The application refuses to
start with `COBBLE_ENV=production`, and the worker logs a warning at start-up.
