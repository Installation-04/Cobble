# 0007 — Demo, validation, agents and costs (steps 8 and 9)

Status: accepted (v0.1, steps 8-9)

## Milestones and demo
- `milestones` table: `project_id`, `ref` (`M1`…, from the plan), `title`, `status` (`pending` → `built` → `validated`; `reverted` returns to `pending`), `tag` (`milestone-M1`), `preview_path`, `built_at`, `validated_at`.
- Per milestone the scheduler appends a synthetic task `DEMO-M1` ("generate realistic demo data", role `worker`, depends on every task of the milestone, files `app/seed.py`). When it is merged the milestone becomes `built`: the scheduler tags the default branch (`GitProvider.tag`), asks the **preview service** to deploy that tag, stores `preview_path`, publishes `milestone.updated`. The project phase stays `building` until every milestone is `validated`, then `done`.
- **Preview service** (`packs/v01/preview-service/`, holds the Docker socket like agent-service): `POST /v1/previews {project_id, milestone, repo_clone_url, ref}` builds the template's Dockerfile at `ref` and runs it (non-root, CPU/RAM limits, TTL idle stop) on a private network; `GET /v1/previews/{id}` → `{state: building|running|failed, path}`; `DELETE /v1/previews/{id}`. It also acts as the reverse proxy for `/demo/<project_id>/<milestone>/…` (prefix stripped); the core Caddy routes `/demo/*` to it. The template serves its built frontend with relative asset paths so it works under a prefix, and runs `app/seed.py` on first start.
- **Capability additions** (Protocols + fakes): `PreviewProvider` (`deploy`, `status`, `remove`), `GitProvider.restore_tag(repo, tag, message)` (a commit on a branch whose tree is the tag's, merged through a normal merge request so CI and protections still apply).

## Demo API (owner-scoped; unsafe methods need the CSRF header)
| Method + path | Body | Success | Errors |
|---|---|---|---|
| `GET /projects/{id}/milestones` | — | `200 [{ref, title, status, tag, preview_path, built_at, validated_at}]` | `404` |
| `POST /projects/{id}/milestones/{ref}/validate` | — | `200 {milestone}` | `409 wrong_state` (not `built`) |
| `POST /projects/{id}/milestones/{ref}/comments` | `{content}` (1–2000) | `201 {task}` — a new task `C-001`… in state `todo` attached to that milestone (role `worker`; the scheduler writes its tests first like any task) | `409 wrong_state` (milestone not `built`/`validated`) |
| `POST /projects/{id}/milestones/{ref}/revert` | — | `202 {}`; restores the tag of the previous milestone (or the template state for `M1`), sets this and later milestones to `pending` and resets their tasks to `todo` | `409 wrong_state` |
A comment re-opens the milestone (`built` → `pending`) and moves a `done` project back to `building`.
Events on the project stream: `milestone.updated {ref, status}`, plus the existing `task.updated`.

## Agents API (step 9, owner-scoped)
- `GET /projects/{id}/tasks`, `GET /projects/{id}/tasks/{ref}` already exist (ADR 0006). Task states gain `paused` and `stopped` semantics as in 0006.
- `GET /projects/{id}/tasks/{ref}/logs?offset=N` → `200 text/plain` chunk of the latest run's log (via the agent runner; falls back to the stored `log_tail`), header `X-Next-Offset`. The UI polls it every 2 s while the task is running.
- `GET /projects/{id}/tasks/{ref}/diff` → `200 {diff, truncated}` unified diff of the task branch against the default branch (empty before the first push).
- `POST /projects/{id}/tasks/{ref}/pause` (state `paused`, no new run; a running run keeps going), `/resume`, `/stop` (stops the current run, state `stopped`), `/retry` (state `todo`, attempts reset, branch reused or recreated). `409 wrong_state` when the transition is not allowed.

## Costs API (step 9, owner-scoped)
- `GET /projects/{id}/costs` → `{budget_usd|null, spent_usd, tokens: {prompt, completion}, estimate_usd|null, by_task: [{ref|null, cost_usd, prompt_tokens, completion_tokens, calls}], by_model: [...], by_role: [...]}` (money as strings with 2–8 decimals). `ref` is null for planner calls (no task).
- `GET /costs` → per project `{project_id, name, spent_usd, budget_usd|null, status}`.

## Fake pack mode (development and CI only)
`COBBLE_PACK_MODE=fake` makes the worker use the in-memory fakes (git, CI, agent runner, preview) instead of Forgejo, Woodpecker, agent-service and preview-service, so the browser e2e can drive the whole build → demo → comment loop in seconds without Docker-in-Docker. The fake agent runner advances through the real scheduler states with short delays and emits believable log lines; the fake preview serves a static demo page at `/demo/<project>/<milestone>/` from the API. The mode is announced loudly in the worker log and in `GET /api/v1/health` (`pack_mode`); it refuses to start when `COBBLE_ENV=production`. The real chain has its own end-to-end harness (`make e2e-full`, manual).

## UI
Project tabs `Agents`, `Demo`, `Costs` (and a "Start building" action on the Plan tab when the phase is `ready`); phase stepper gains `Building` and `Done`; global views `/agents`, `/demos`, `/costs` list projects with their totals and link into the tabs. All strings fr+en, tokens only, accessible.
