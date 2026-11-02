# 0007 — Demo, validation, agents and costs (steps 8 and 9)

Status: accepted (v0.1, steps 8-9)

## Milestones and demo
- `milestones` table: `project_id`, `ref` (`M1`…, from the plan), `title`, `status` (`pending` → `built` → `validated`; `reverted` returns to `pending`), `tag` (`milestone-M1`), `preview_path`, `built_at`, `validated_at`.
- Per milestone the scheduler appends a synthetic task `DEMO-M1` ("generate realistic demo data", role `worker`, depends on every task of the milestone, files `app/seed.py`). When it is merged the milestone becomes `built`: the scheduler tags the default branch (`GitProvider.tag`), asks the **preview service** to deploy that tag, stores `preview_path`, publishes `milestone.updated`. The project phase stays `building` until every milestone is `validated`, then `done`.
- **Preview service** (`services/preview-service/` since v0.2, shipped by the `preview` module; holds the Docker socket like agent-service): `POST /v1/previews {project_id, milestone, repo_clone_url, ref}` builds the template's Dockerfile at `ref` and runs it (non-root, CPU/RAM limits, TTL idle stop) on a private network; `GET /v1/previews/{id}` → `{state: building|running|failed, path}`; `DELETE /v1/previews/{id}`. It also acts as the reverse proxy for `/demo/<project_id>/<milestone>/…` (prefix stripped); the core Caddy routes `/demo/*` to it. The template serves its built frontend with relative asset paths so it works under a prefix, and runs `app/seed.py` on first start.
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

## Implementation notes — Agents and costs
- **Controls** live in `scheduler/control.py`: a pure `decide(action, facts) -> Decision` (table-tested) and `apply()` (database, `AgentRunner.stop`, `task.updated`). They answer `200` with the task (`TaskOut`), `409 wrong_state {state}`, or `503 agent_unavailable` (nothing changed) when a live run cannot be stopped. The state table is in the module docstring and in `docs/*/costs-agents.md`.
- **Operator pause vs. scheduler pause.** The scheduler already parks tasks as `paused` (no slot, budget). An operator pause is the same state with `last_error` prefixed by `user_paused` (no schema change; the previous error is kept after the prefix and restored on resume). The engine shows such a task to `rules` as the pseudo-state `held`, so it is neither started nor takes files. A run already running keeps going but is not polled until `resume`, which re-attaches it by returning the task to `writing_tests`/`implementing`/`ci`.
- **Stop** asks the agent service to stop each active run, then closes the rows as `stopped`; a `stopped` task is never started by `tick`/`reconcile`. If the service is unreachable nothing changes.
- **Retry** marks the previous worker runs (and failed test-writer runs) `retired` so the attempt counter of the scheduler restarts at zero while the logs stay; it clears `pr_number` (the open pull request of the branch pair is reused) and returns `blocked` tasks that only waited on this one to `todo`.
- **Capabilities** (additive): `AgentRunner.logs(run_id, offset) -> (text, next_offset)`; `GitProvider.diff(repo, base, head, *, request_number=None) -> (text, truncated)` with `DIFF_LIMIT` 200 000 characters, cut on a line. Forgejo: `pulls/{n}.diff` (the number is passed once a pull request exists, so merged tasks still have a diff), else `pulls/{base}/{head}`, else `compare/{base}...{head}.diff`; unknown branch gives an empty diff.
- **API wiring**: the routes read `app.state.agents` / `app.state.git` when set, else build the pack services once from the settings (`None` without pack tokens: logs fall back to `log_tail`, diff and stop answer 503).
- **Costs** (`cobble/costs.py`): three grouped queries over `llm_calls` (outer join to `tasks` for the ref) plus one for the plan estimate; money is `Decimal`, rendered with 2-8 decimals, trailing zeros trimmed (`"0.0215"`, `"0.20"`). `by_task` ascending by task number, planner/orphan calls (`ref: null`) last; `by_model`/`by_role` by decreasing cost. `estimate_usd` is the approved plan's `estimate.cost_usd`, else the latest plan's.

## Implementation notes (demo side, step 8)
- **Demo flow is optional.** `Scheduler(preview=...)`: without a `PreviewProvider` nothing below applies and a project is `done` when every task is merged (ADR 0006 behaviour). The real pack enables it when `COBBLE_PREVIEW_SERVICE_TOKEN` is set; the fake pack always does.
- **Schema (migration 0007).** `milestones(project_id, ref, title, status, tag, preview_path, preview_state, revision, built_at, validated_at)` and `tasks.kind` (`plan|demo|comment|revert`). `preview_state` (`building|running|failed`) and `revision` are additions to the ADR table; `preview_state` is exposed by `GET .../milestones` and in `milestone.updated {ref, status, preview_state}`. `revision` names the next tag (`milestone-M1`, `-r2`, ...): a tag is never reused.
- **Synthetic tasks.** `DEMO-Mx` (kind `demo`, role `worker`, files `app/seed.py`, tests `n/a`: no test-writer step, local test command is the whole suite). Comments are `C-001`... (kind `comment`, files `["*"]`: a task touching any file never runs beside another active task; its single acceptance criterion is the comment). Reverts add `R-001`... (kind `revert`, files `["*"]`, acceptance `restore:<tag>`): the scheduler asks `GitProvider.restore_tag`, then the usual CI and merge steps; a red CI fails it (no agent is asked to fix a restore) and the reset tasks of the reverted milestones depend on it.
- **Resumability.** Milestone progress is derived from the database at every tick: `pending` + all tasks merged -> tag (stored only after git has it; `TagExists` counts as done) -> deploy (retried while the preview service is down) -> `built`. `reconcile()` runs the same step.
- **Revert is a job.** `POST .../revert` checks the state (`409 wrong_state`) and queues `{"kind":"revert","project_id","ref"}`; the worker calls `Scheduler.run_revert_job`, which stops running agent runs of the reset tasks, deletes their runs and removes the previews.
- **`GitProvider.restore_tag(repo, tag, message) -> MergeRequestRef | None`**: ForgejoGit clones, creates a commit with the tag's tree and the head of the default branch as parent, force-pushes it to `restore/<tag>` and opens the merge request; `None` when the tree is already in place. The first commit of the repository is tagged `template-initial` at project start (revert of `M1`).
- **Preview service.** Build through the classic Engine API builder (`POST /build`, tar context without `.git`): the template Dockerfile therefore avoids BuildKit-only syntax. Containers always run as `10001:10001` with `/tmp` as the only writable path. Previews are public, sandboxed (CSP `sandbox`, CORS answered by the proxy) and stop when idle. Verified live: see docs/en/demo.md.
- **Fake pack mode.** `Settings` refuses `pack_mode=fake` with `env=production`; `SimulatedAgentRunner` and `StatelessFakeGit` derive everything from their arguments (the run id carries start time, role, task and branch), so the API and the worker processes agree.
- **Deviations.** The `DEMO` task's `role` is `worker` as written above even though task roles elsewhere are areas; the milestone tag is placed on the head of the default branch when the scheduler notices the `DEMO` merge, not on the exact merge commit.
