# 0006 — Agent runner, internal LLM endpoint and scheduler (step 7)

Status: accepted (v0.1, step 7)

## Principles
- **Only the pack service touches Docker (rule 5).** `agent-service` (in `packs/v01/agent-service/`) holds the Docker socket and exposes a small internal HTTP API. The backend implements the `AgentRunner` capability as an HTTP client of it (`backend/cobble/providers/agent_service.py`). Agent containers never get the socket, run as non-root, with CPU/RAM/PID/time limits, a read-only root filesystem except the worktree and `/tmp`, and no capabilities.
- **Agent containers hold no git credentials.** `agent-service` clones the repository into a per-run worktree on a host volume, mounts it into the container, and after the container exits it checks the result and pushes the task branch itself.
- **Agents never call a model provider or LiteLLM directly (rule 2).** They call the **internal LLM endpoint** of the Cobble API, which applies the project budget, maps the role to a model, goes through LiteLLM and records tokens/cost with `project_id` and `task_id` in `llm_calls`.
- **Egress**: the agent container sits on an internal network `cobble_agents` whose only exits are an allowlist HTTP proxy (`agent-proxy`) permitting the API's internal endpoint and the package registries (PyPI, npm). Not LiteLLM, not Forgejo.

## Internal LLM endpoint (backend API)
`POST /internal/llm/v1/chat/completions` — OpenAI-compatible, non-streaming (agents run with streaming off). Not routed by Caddy (reachable only on the internal networks). `Authorization: Bearer <run token>`.
- **Run token**: stateless, HMAC-SHA256 signed with `COBBLE_RUN_TOKEN_SECRET` (generated into `.env`): payload `{task_id, project_id, role, exp}`, lifetime = the run's `max_seconds` + 60 s. Created by the scheduler and passed to `agent-service`, which passes it to the container as the OpenAI API key.
- The request's `model` field is ignored: the model is `CostRouter.model_for(role)` (role from the token; the scheduler passes the model to use after an escalation as `model_override` inside the token's payload, never from the request).
- Errors: `401 invalid_token`, `402 budget_reached` (project paused: the router raises `BudgetExceeded`), `502 llm_error`. Bodies use the standard `{"error": {"code", "params"}}` shape.

## agent-service HTTP API (internal, `Authorization: Bearer <COBBLE_AGENT_SERVICE_TOKEN>`)
| Method + path | Body | Success |
|---|---|---|
| `POST /v1/runs` | `{task_id, project_id, repo_clone_url, base_branch, branch, role, model, instructions, files: [..], test_command, limits: {max_iterations, max_seconds, cpu, memory_mb, pids}, run_token, marker}` | `202 {run_id}` |
| `GET /v1/runs/{run_id}` | — | `200 {state, iterations, exit_code, head_sha, log_tail}` with `state` ∈ `running`, `done`, `failed`, `timeout`, `loop_detected`, `stopped` |
| `GET /v1/runs/{run_id}/logs?offset=N` | — | `200 text/plain` chunk + header `X-Next-Offset` |
| `POST /v1/runs/{run_id}/stop` | — | `204` |
| `GET /healthz` | — | `200` |
`marker` (`[cobble-task:<task>:<role>:<attempt>]`) is prepended to the instructions so tests can replay cassettes by marker (see the fake LLM README). Loop detection: the same normalized output line repeated `COBBLE_LOOP_THRESHOLD` (default 8) times in a row, or the same test-failure fingerprint twice in a row, ends the run with `loop_detected`.

## Scheduler (backend `cobble/scheduler/`, run by the worker)
- Tables `tasks` (from the approved plan: id `T-001`, milestone, depends_on, files, acceptance, tests, size, role, state, attempts, escalated, branch, pr_number, last_error) and `task_runs` (task, role, attempt, model, state, run_id in agent-service, started/finished, log reference). States: `todo → writing_tests → implementing → ci → merged | failed | blocked`, plus `paused` and `stopped`.
- Starting a project (`POST /projects/{id}/start`, phase `ready` → `building`) materializes the tasks from the approved plan.
- A task is runnable when its dependencies are `merged` and its `files` do not overlap those of any running task. Concurrency limit `COBBLE_MAX_PARALLEL_AGENTS` (default 2).
- Per task: `test-writer` run (writes the tests listed in `tests`), then `worker` run until the tests pass locally, push, open a merge request, wait for CI, merge if green (the git provider refuses otherwise). CI red → one more worker attempt with the CI log; after `COBBLE_ESCALATE_AFTER` (default 2) failed attempts the worker role is escalated (model override to the `escalation` model, default = planner's model); a further failure marks the task `failed` and blocks its dependents.
- Guardrails: per-run `max_iterations`/`max_seconds` (enforced by agent-service); `loop_detected` counts as a failure; `budget.reached` pauses the project and no new run starts.
- **Resumable**: all state is in the database. On worker start the scheduler reconciles: runs still `running` are re-attached to their agent-service run (or marked failed if the service lost them), merge requests already open are re-checked, nothing is done twice.
- Events on the project stream: `task.updated {task_id, state}`, `project.building`, `project.done`.

## Implementation notes (scheduler, step 7)

**Settings** (all `COBBLE_*`, in `cobble/config.py`): `MAX_PARALLEL_AGENTS` (2), `ESCALATE_AFTER` (2), `MAX_ATTEMPTS` (4), `ESCALATION_MODEL` (empty = the `planner` role's model), `TEMPLATE_DIR` (`/templates/fastapi-react`, must be mounted in the worker), `SCHEDULER_INTERVAL_S` (5), `BASE_BRANCH` (`main`), `CI_TIMEOUT_S` (1800), `AGENT_MAX_ITERATIONS` (20), `AGENT_MAX_SECONDS` (900), `AGENT_CPU` (1.0), `AGENT_MEMORY_MB` (2048), `AGENT_PIDS` (256). Existing: `RUN_TOKEN_SECRET`, `AGENT_SERVICE_URL`, `AGENT_SERVICE_TOKEN`. The pack's own settings are `COBBLE_PACK_*`; `COBBLE_PACK_ENV_FILE` may name an env file for them. Without `RUN_TOKEN_SECRET`, `AGENT_SERVICE_TOKEN` or the pack tokens the worker logs why and runs without a scheduler (planning keeps working; a `start` job then answers `job.failed {code: scheduler_unavailable}`).

**Start**: `POST /api/v1/projects/{id}/start` (owner only, CSRF) checks `phase == ready` (409 `wrong_phase`) and `status == active` (409 `project_paused`), then queues the job `{"kind": "start", "project_id"}` on `cobble:jobs` (202, `{}`): creating the repository pushes the template, which is too slow for a request. The jobs loop runs `Scheduler.run_start_job`: events `job.started {kind: start}`, then `phase.changed {phase: building}` + `project.building {tasks}`, or `job.failed {kind: start, code}` with `repo_error`, `ci_error`, `no_plan`, `wrong_phase`, `internal_error`. `start_project` is idempotent (the repository is saved before anything else can fail and reused on a retry).

**Events** on the project stream: `task.updated {task_id: "T-001", state, attempts}` on every state change (and on every new worker attempt), `project.building`, `project.done {tasks}`, plus `phase.changed` for `building` and `done`. Project phases now include `building` and `done`.

**Task states**: `paused` means "needs a new run but cannot start it now" (project budget reached, or no free agent slot after a CI retry); the scheduler resumes it first. A budget-stopped run (`AgentOutcome.BUDGET`) parks the task and does not use an attempt. `stopped` is a run that ended on request. Run states in `task_runs`: `pending` (row written before calling the agent service), `running`, the agent outcome (`done`, `failed`, `timeout`, `loop_detected`, `stopped`, `budget`), `rejected` (agent done but CI or the merge said no), `lost` (interrupted before the run id was stored; not counted).

**Attempts**: attempt N of the worker = failed worker attempts so far + 1 (`done`, `failed`, `timeout`, `loop_detected`, `rejected` count). Escalation when failed attempts >= `ESCALATE_AFTER` (the run token carries `model_override`), `failed` when they reach `MAX_ATTEMPTS`, dependents `blocked`. The test-writer is retried up to `MAX_ATTEMPTS` times (marker attempt always 1), then the task fails. Deviation from the ADR text ("a further failure marks the task failed"): with the defaults that is attempts 1-2 normal, 3-4 escalated, failure after the fourth.

**CI and merge**: CI is read with `CIProvider.status(repo, head_sha)` (the run's `head_sha`, or the branch name when the service gave none), so a retry never reads the previous attempt's pipeline. The CI log available to the next attempt is `CIStatus.detail`. A pending CI older than `CI_TIMEOUT_S` counts as a failed attempt. `MergeRefused` is treated as a CI problem (new attempt); any other provider exception is logged and retried on the next tick without using an attempt. `open_merge_request` and `merge` must be idempotent (the Forgejo provider is): that is what makes a crash between the merge and its record harmless.

**Agent protocol**: the instructions start with the marker line, and the marker is also sent as the `marker` field (the agent service may therefore prepend it only if the instructions do not already start with it). `AgentRunner` is now `start(task) -> run_id`, `poll(run_id) -> AgentResult | None`, `stop(run_id)`, `run(task)`; `AgentUnavailable` (service down, 5xx, 429) is retried and never counted, `AgentRunNotFound` marks the attempt failed, `AgentRejected` (400/401/403/409/422 on start) counts as a failed attempt.

**Resumption**: `reconcile()` (run once when the scheduler thread starts) marks `pending` runs `lost`, then processes the runs still `running` by polling them again, and re-checks the merge requests in `ci`. A single scheduler instance is assumed (the single worker of v0.1); two would need a lock. A crash right after the agent service accepted a run but before its id was stored can leave an orphan container, ended by its time limit.

**Wiring for the lead**: the worker needs `COBBLE_RUN_TOKEN_SECRET`, `COBBLE_AGENT_SERVICE_URL`, `COBBLE_AGENT_SERVICE_TOKEN`, the `COBBLE_PACK_*` variables (or `COBBLE_PACK_ENV_FILE`), and the template directory mounted read-only at `COBBLE_TEMPLATE_DIR`. The API container needs `COBBLE_RUN_TOKEN_SECRET` for the internal LLM endpoint (already the case).
